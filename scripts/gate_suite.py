#!/usr/bin/env python3
"""Release-gate integration scenarios: actual TLS negotiation and atomic promotion."""
import argparse,json,os,subprocess,sys,time,shlex
from datetime import datetime,timezone
from pathlib import Path

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
def cmd(role,command,data=None):
    ssh=['ssh','-i',str(ROOT/'kpqc-devops-lab.pem'),'-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlias='+ALIASES[role],'-o',f'UserKnownHostsFile={ROOT}/.aws-runtime/known_hosts','-o','ControlMaster=auto','-o','ControlPersist=600','-o',f'ControlPath={ROOT}/.aws-runtime/gate-%h','-o','ConnectTimeout=10']
    p=subprocess.run([*ssh,'ubuntu@'+HOSTS[role],command],input=data,capture_output=True,timeout=180)
    if p.returncode:raise RuntimeError(role+': '+p.stderr.decode(errors='replace')[-3000:])
    return p.stdout
def worker(role,q):
    if args.local:return gate_worker.main(q)
    return json.loads(cmd(role,'sudo docker exec -i kpqc-gate python3 /app/scripts/gate_worker.py',json.dumps(q).encode()))
result={'status':'running','run_id':RUN,'environment_kind':'local loopback' if args.local else 'AWS same-AZ private IPv4','scenarios':[],'probes':[],'assertions':[]}
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
            cmd(role,f'mkdir -p kpqc-devops-lab/results/{RUN} && sudo docker run -d --init --name kpqc-gate --network host --cpus 2 --memory 512m --tmpfs /state:rw,noexec,nosuid,size=64m -v "$HOME/kpqc-devops-lab/results/{RUN}:/results" {shlex.quote(args.image)}')
            started.append(role)
    init=worker('server',{'action':'init-server'});recv=worker('client',{'action':'init-client','trust':init['trust']})
    result['policy']=init['policy'];result['certificate_sha256']=init['certificate_sha256'];result['server_environment']=init['environment'];result['client_environment']=recv['environment']
    verify('source_hashes_match',init['environment']['source_sha256']==recv['environment']['source_sha256'])
    verify('initial_active_pqc',probe(tag='initial-active')['policy_failure'] is None)
    worker('client',{'action':'monitor-start','ip':IP});monitor=True
    for name,expected in [('wrong-kem','KEM_POLICY_MISMATCH'),('wrong-signature','SIGNATURE_POLICY_MISMATCH'),('missing-provider','PROVIDER_UNAVAILABLE'),('good-v2',None)]:
        before=worker('server',{'action':'state'});start=worker('server',{'action':'candidate','name':name})
        probes={}
        if start['ready']:
            for client in ['broad','pqc','legacy']:probes[client]=probe('candidate',client,'all',f'{name}-{client}')
        evidence={'ready':start['ready'],'startup_reason':start.get('reason'),'probes':probes,'required_clients':['pqc']}
        decision=worker('server',{'action':'decision',**evidence})
        verify(name+'-expected-decision',decision['deployment_allowed']==(expected is None))
        if expected:
            verify(name+'-reason',expected in decision['reasons'])
            if start['ready']:verify(name+'-broad-handshake-succeeded',probes['broad']['success'] and probes['broad']['verify_result']==0)
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
            legacy_evidence={**evidence,'required_clients':['pqc','legacy']}
            legacy=worker('server',{'action':'decision',**legacy_evidence})
            verify('required-legacy-blocks-promotion',not legacy['deployment_allowed'] and 'REQUIRED_CLIENT_INCOMPATIBLE' in legacy['reasons'])
            verify('legacy-block-keeps-active',worker('server',{'action':'state'})['active']==before['active'])
            scenario['required_legacy_decision']=legacy
            promoted=worker('server',{'action':'promote','candidate':name,'evidence':evidence})
            verify('approved-candidate-promoted',promoted['active']['version']=='good-v2')
            result['promotion']=promoted
            for i in range(5):verify(f'promoted-cert-and-pqc-{i}',probe(trust='good-v2',tag=f'promoted-{i}')['policy_failure'] is None)
        (OUT/'results.json').write_text(json.dumps(result,indent=2))
    result['monitor']=worker('client',{'action':'monitor-stop'});monitor=False
    verify('active-monitor-has-samples',result['monitor']['samples']>=2)
    verify('active-monitor-no-policy-failures',result['monitor']['failed']==0)
    result['status']='passed'
except Exception as e:
    result['status']='failed';result['error']=repr(e);raise
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
