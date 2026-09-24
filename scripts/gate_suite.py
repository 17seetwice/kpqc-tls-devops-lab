#!/usr/bin/env python3
"""Release-gate integration scenarios: actual TLS negotiation and atomic promotion."""
import argparse,json,os,subprocess,sys,time,shlex
from datetime import datetime,timezone
from pathlib import Path

# 이 파일은 실험의 시나리오다: 기존 서비스 준비 → 오류·혼합 후보 차단 → 연속 정상 후보 승격 → 결과 수집.
# --local은 같은 컨테이너의 loopback, AWS 모드는 SSH로 두 컨테이너의 작업자를 호출한다.
ap=argparse.ArgumentParser();ap.add_argument('--local',action='store_true');ap.add_argument('--server');ap.add_argument('--client');ap.add_argument('--server-private',default=os.environ.get('KPQC_SERVER_PRIVATE'));ap.add_argument('--image',default='kpqc-lab:gate');args=ap.parse_args()
RUN=datetime.now(timezone.utc).strftime(('local-gate-' if args.local else 'aws-gate-')+'%Y%m%dT%H%M%SZ')
ROOT=Path(__file__).resolve().parents[1]
OUT=(Path('/results-root') if args.local else ROOT/'artifacts')/RUN;OUT.mkdir(parents=True)
if args.local:
    Path('/results').symlink_to(OUT,target_is_directory=True)
    import gate_worker
    IP='127.0.0.1'
else:
    assert args.server and args.client and args.server_private;IP=args.server_private
HOSTS={'server':args.server,'client':args.client};ALIASES={role:os.environ.get('KPQC_'+role.upper()+'_HOST_ALIAS', 'kpqc-'+role) for role in HOSTS}
# 제어 명령과 JSON 증적을 SSH로 주고받는다. TLS 성능 측정 구간에 이 SSH 왕복 시간은 포함하지 않는다.
def cmd(role,command,data=None):
    ssh=['ssh','-i',str(ROOT/'kpqc-devops-lab.pem'),'-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlias='+ALIASES[role],'-o',f'UserKnownHostsFile={ROOT}/.aws-runtime/known_hosts','-o','ControlMaster=auto','-o','ControlPersist=600','-o',f'ControlPath={ROOT}/.aws-runtime/gate-%h','-o','ConnectTimeout=10']
    p=subprocess.run([*ssh,'ubuntu@'+HOSTS[role],command],input=data,capture_output=True,timeout=180)
    if p.returncode:raise RuntimeError(role+': '+p.stderr.decode(errors='replace')[-3000:])
    return p.stdout
# 로컬과 AWS가 동일한 gate_worker.main() 동작을 쓰도록 호출 방법만 분리한다.
def worker(role,q):
    if args.local:return gate_worker.main(q)
    return json.loads(cmd(role,'sudo docker exec -i kpqc-gate python3 /app/scripts/gate_worker.py',json.dumps(q).encode()))
result={'status':'running','run_id':RUN,'environment_kind':'local loopback' if args.local else 'AWS same-AZ private IPv4','scenarios':[],'probes':[],'assertions':[]}
# 배포 승인 여부와 시험 성공 여부는 다르다. 잘못된 후보를 예상대로 차단하면 시험은 통과다.
def verify(name,ok):
    result['assertions'].append({'name':name,'passed':bool(ok)})
    assert ok,name
def probe(route='active',client='pqc',trust='active-v1',tag=None):
    r=worker('client',{'action':'probe','ip':IP,'route':route,'client':client,'trust':trust,'tag':tag})
    result['probes'].append(r);return r
started=[];monitor=False
try:
    if not args.local:
        for role in HOSTS:
            cmd(role,f'mkdir -p kpqc-devops-lab/results/{RUN} && sudo docker run -d --init --name kpqc-gate --network host --cpus 2 --memory 512m --tmpfs /state:rw,noexec,nosuid,size=64m -e KPQC_IMAGE_ID={shlex.quote(os.environ.get('KPQC_IMAGE_ID','local-unattested'))} -v "$HOME/kpqc-devops-lab/results/{RUN}:/results" {shlex.quote(args.image)}')
            started.append(role)
    # 기존 활성 서비스와 후보별 인증서를 만든다. 클라이언트에는 신뢰할 공개 인증서만 전달한다.
    init=worker('server',{'action':'init-server'});recv=worker('client',{'action':'init-client','trust':init['trust']})
    result['policy']=init['policy'];result['certificate_sha256']=init['certificate_sha256'];result['server_environment']=init['environment'];result['client_environment']=recv['environment']
    verify('source_hashes_match',init['environment']['source_sha256']==recv['environment']['source_sha256'])
    result['tls12_positive_control']=worker('server',{'action':'tls12-control'})
    verify('tls12-probe-positive-control',result['tls12_positive_control']['passed'])
    verify('initial_active_pqc',probe(tag='initial-active')['policy_failure'] is None)
    # 후보 시험과 동시에 활성 경로를 반복 접속한다. 표본 감시이며 모든 순간의 무중단을 증명하지 않는다.
    worker('client',{'action':'monitor-start','ip':IP});monitor=True
    # expected는 해당 후보에서 기대하는 차단 사유다. None인 good-v2만 승격할 수 있다.
    for name,expected in [('wrong-kem','KEM_POLICY_MISMATCH'),('wrong-signature','SIGNATURE_POLICY_MISMATCH'),('mixed-kem','CLASSICAL_FALLBACK_ACCEPTED'),('mixed-signature','CLASSICAL_FALLBACK_ACCEPTED'),('good-v2',None)]:
        before=worker('server',{'action':'state'});start=worker('server',{'action':'candidate','name':name})
        probes={}
        if start['ready']:
            # broad는 고전/PQC 모두 제안, pqc는 승인한 PQC만 제안, legacy는 고전 방식만 제안한다.
            # 넓게 허용한 연결이 성공해도 실제 협상 결과가 정책에 맞는지는 별도로 판정한다.
            for client in ['broad','pqc','classical_kem','classical_signature','legacy','tls12']:probes[client]=probe('candidate',client,'all',f'{name}-{client}')
        evidence={'binding':start.get('route',{}).get('candidate'),'ready':start['ready'],'startup_reason':start.get('reason'),'probes':probes,'required_clients':['pqc']}
        decision=worker('server',{'action':'decision',**evidence})
        verify(name+'-expected-decision',decision['deployment_allowed']==(expected is None))
        if expected:
            verify(name+'-reason',expected in decision['reasons'])
            if start['ready']:verify(name+'-broad-handshake-succeeded',probes['broad']['success'] and probes['broad']['verify_result']==0)
        if name=='mixed-kem':
            verify('mixed-kem-pqc-still-succeeds',probes['pqc']['policy_failure'] is None)
            verify('mixed-kem-classical-only-succeeds',probes['classical_kem']['success'])
        if name=='mixed-signature':
            verify('mixed-signature-pqc-succeeds',probes['pqc']['policy_failure'] is None)
            verify('mixed-signature-ecdsa-succeeds',probes['classical_signature']['success'])
        # 후보를 검사하는 것만으로 기존 서비스가 바뀌면 안 된다. 경로 상태와 실제 TLS 접속을 함께 확인한다.
        after=worker('server',{'action':'state'});verify(name+'-active-unchanged',before['active']==after['active'])
        active=probe(tag=name+'-active-check');verify(name+'-active-still-pqc',active['policy_failure'] is None)
        scenario={'candidate':name,'startup':start,'probes':probes,'decision':decision,'active_before':before['active'],'active_after_gate':after['active'],'active_probe':active}
        result['scenarios'].append(scenario)
        if expected:
            scenario['discard']=worker('server',{'action':'discard'})
            state=worker('server',{'action':'state'})
            verify(name+'-candidate-discarded',state['candidate'] is None and state['active']==before['active'])
        print(name,decision,flush=True)
        if name=='good-v2':
            # 같은 정상 PQC 후보도 legacy 지원을 필수로 요구하는 정책에서는 차단되어야 한다.
            legacy_evidence={**evidence,'required_clients':['pqc','legacy']}
            legacy=worker('server',{'action':'decision',**legacy_evidence})
            verify('required-legacy-blocks-promotion',not legacy['deployment_allowed'] and 'REQUIRED_CLIENT_INCOMPATIBLE' in legacy['reasons'])
            verify('legacy-block-keeps-active',worker('server',{'action':'state'})['active']==before['active'])
            scenario['required_legacy_decision']=legacy
            import copy
            for kind in ['generation','certificate','policy','image','stale','timeout','malformed']:
                bad=copy.deepcopy(evidence)
                if kind in ['generation','policy','image']:
                    key={'generation':'generation','policy':'policy_sha256','image':'image_identity'}[kind];bad['binding'][key]='wrong'
                elif kind=='certificate':bad['probes']['pqc']['peer_certificate_sha256']='0'*64
                elif kind=='stale':bad['probes']['pqc']['observed_at_ns']=0
                else:bad['probes']['pqc']=worker('client',{'action':'probe','ip':IP,'route':'candidate','client':'pqc','trust':'all','tag':'fault-'+kind,'fault':kind})
                rejected=worker('server',{'action':'decision',**bad})
                result.setdefault('fault_checks',[]).append({'fault':kind,'decision':rejected,'probe_error':bad['probes']['pqc'].get('probe_error')})
                verify('reject-evidence-'+kind,not rejected['deployment_allowed'])
                verify('fault-'+kind+'-active-survives',probe(tag='fault-active-'+kind)['policy_failure'] is None)
            # 승인된 후보만 활성 경로로 전환한다. 이후 새 인증서만 신뢰하는 접속 5회로 전환을 확인한다.
            promoted=worker('server',{'action':'promote','candidate':name,'evidence':evidence})
            verify('approved-candidate-promoted',promoted['active']['version']=='good-v2')
            result['promotion']=promoted
            for i in range(5):verify(f'promoted-cert-and-pqc-{i}',probe(trust='good-v2',tag=f'promoted-{i}')['policy_failure'] is None)
        (OUT/'results.json').write_text(json.dumps(result,indent=2))
    # Regression: a rejected candidate after promotion must not kill the new active PID.
    before=worker('server',{'action':'state'})
    worker('server',{'action':'candidate','name':'wrong-kem'})
    worker('server',{'action':'discard'})
    verify('post-promotion-discard-keeps-active',worker('server',{'action':'state'})['active']==before['active'])
    verify('post-promotion-active-connects',probe(trust='good-v2',tag='after-discard')['policy_failure'] is None)
    start=worker('server',{'action':'candidate','name':'good-v3'})
    probes={c:probe('candidate',c,'all','good-v3-'+c) for c in ['broad','pqc','classical_kem','classical_signature','legacy','tls12']}
    evidence={'binding':start.get('route',{}).get('candidate'),'ready':start['ready'],'probes':probes,'required_clients':['pqc']}
    second=worker('server',{'action':'promote','candidate':'good-v3','evidence':evidence})
    verify('second-promotion-succeeds',second['active']['version']=='good-v3')
    verify('second-promotion-connects',probe(trust='good-v3',tag='after-second-promotion')['policy_failure'] is None)
    worker('server',{'action':'discard'})
    verify('empty-discard-keeps-active',probe(trust='good-v3',tag='after-empty-discard')['policy_failure'] is None)
    result['second_promotion']=second
    result['monitor']=worker('client',{'action':'monitor-stop'});monitor=False
    verify('active-monitor-has-samples',result['monitor']['samples']>=2)
    verify('active-monitor-no-policy-failures',result['monitor']['failed']==0)
    result['status']='passed'
except Exception as e:
    result['status']='failed';result['error']=repr(e);raise
# 성공·실패 모두 증적을 기록하고 컨테이너를 정리한다. 이 시험은 지속 운영 배포가 아닌 일시적 PoC다.
finally:
    if monitor:
        try:result['monitor']=worker('client',{'action':'monitor-stop'})
        except Exception as e:result.setdefault('cleanup_errors',[]).append(str(e))
    for role in (['server'] if args.local else started):
        try:
            worker(role,{'action':'cleanup'})
            if not args.local:
                (OUT/f'{role}-evidence.tar.gz').write_bytes(cmd(role,f'sudo tar -czf - -C "$HOME/kpqc-devops-lab/results/{RUN}" .'))
                cmd(role,'sudo docker rm -f kpqc-gate')
        except Exception as e:result.setdefault('cleanup_errors',[]).append(role+': '+str(e))
    (OUT/'results.json').write_text(json.dumps(result,indent=2));print('RESULTS:',OUT,flush=True)
