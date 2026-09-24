#!/usr/bin/env python3
"""Lab-only deployment worker, TCP control router and sampled active monitor."""
import hashlib,json,os,select,signal,socket,ssl,subprocess,sys,threading,time,uuid
from pathlib import Path
import handshake_worker

# 이 파일은 실험 동작을 수행하는 작업자다. main(q)의 action으로 서버 준비·후보 실행·검증·승격을 선택한다.
# /state는 개인키와 프로세스 상태를 두는 tmpfs, /results는 수집할 결과·로그를 두는 경로다.
STATE=Path('/state');OUT=Path('/results');BIN='/app/tls_handshake'
POLICY=json.loads(Path('/app/policies/pqc-required.json').read_text())
# 임시 파일을 완성한 뒤 원자적으로 교체해 라우터가 절반만 기록된 JSON을 읽지 않게 한다.
def save(p,v):
    tmp=Path(str(p)+'.'+uuid.uuid4().hex);tmp.write_text(json.dumps(v,indent=2));os.replace(tmp,p)
# 핵심 배포 정책: TLS 연결 성공 + 인증서 검증 성공 + 실제 협상된 버전/KEM/서명/대칭암호 일치.
# 서버의 설정 문자열이 아니라 C 측정기가 관측한 결과를 검사한다.
def check(r):
    if not r or not r.get('success') or r.get('returncode')!=0:return 'TLS_HANDSHAKE_FAILED'
    if r['verify_result']!=0:return 'CERTIFICATE_VERIFICATION_FAILED'
    for key,want,reason in [('tls_version',POLICY['tls_version'],'TLS_VERSION_MISMATCH'),('group_code',POLICY['group_code'],'KEM_POLICY_MISMATCH'),('signature_code',POLICY['signature_code'],'SIGNATURE_POLICY_MISMATCH'),('cipher',POLICY['cipher'],'CIPHER_POLICY_MISMATCH')]:
        if r[key]!=want:return reason
    return None
def read(p):return json.loads(p.read_text())
# 서버가 fork한 자식까지 종료하도록 프로세스 그룹에 신호를 보낸다.
def stop(pid):
    try:os.killpg(pid,signal.SIGTERM)
    except ProcessLookupError:pass
# 이전 후보의 포트가 닫힌 후 다음 후보를 띄워 같은 포트 재사용 충돌을 피한다.
def wait_listen(port):
    for _ in range(300):
        if not any(x.split()[1].endswith(f':{port:04X}') and x.split()[3]=='0A' for x in Path('/proc/net/tcp').read_text().splitlines()[1:]):return
        time.sleep(.01)
    raise RuntimeError('listener not closed')
# 인증서·키·KEM·서명 파라미터를 지정해 C TLS 서버를 실행하고 listen 준비를 기다린다.
def launch(name,group,sig,port):
    prefix=OUT/name;log=open(OUT/f'{name}.stderr','wb')
    p=subprocess.Popen([BIN,'server',group,handshake_worker.sigalg(sig),str(STATE/f'{name}.crt'),str(STATE/f'{name}.key'),'127.0.0.1',str(port),str(prefix),'10000','kpqc-lab.internal'],stdout=log,stderr=log,start_new_session=True);log.close()
    for _ in range(300):
        if Path(str(prefix)+'.ready').exists():return p.pid
        if p.poll() is not None:raise RuntimeError('server launch failed')
        time.sleep(.01)
    raise RuntimeError('readiness timeout')
# TLS 암호문을 해독하지 않고 TCP 바이트를 양방향으로 전달하는 실험용 중계기다.
def relay(a,b):
    try:
        while True:
            ready,_,_=select.select([a,b],[],[],20)
            if not ready:return
            for src in ready:
                buf=src.recv(65536)
                if not buf:return
                (b if src is a else a).sendall(buf)
    except OSError:pass
    finally:a.close();b.close()
# 연결마다 active/candidate 접속 대상을 고른다. 일반 HTTPS용 로드밸런서가 아니다.
def router():
    def serve(c):
        try:
            c.settimeout(5);label=b''
            while not label.endswith(b'\n') and len(label)<16:
                b=c.recv(1)
                if not b:raise ValueError('missing selector')
                label+=b
            # TLS 전에 보낸 실험용 평문 선택자를 소비한 뒤 TLS 바이트만 대상 서버에 중계한다.
            kind=label.strip().decode();assert kind in ['active','candidate']
            state=read(STATE/'route.json');target=state[kind];assert target
            up=socket.create_connection(('127.0.0.1',target['port']),timeout=5)
            with open(OUT/'router.jsonl','a') as f:f.write(json.dumps({'time_ns':time.time_ns(),'route':kind,'version':target['version'],'port':target['port']})+'\n')
            c.settimeout(None);up.settimeout(None);relay(c,up)
        except Exception:c.close()
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('0.0.0.0',4433));listener.listen(32)
        (STATE/'router.ready').write_text('ready')
        while True:
            c,_=listener.accept();threading.Thread(target=serve,args=(c,),daemon=True).start()
# C 클라이언트를 새 프로세스로 실행한다. trust는 인증서 검증에 사용할 신뢰 묶음을 선택한다.
def probe(ip,route,client='broad',trust='all',tag=None):
    tag=tag or ('probe-'+uuid.uuid4().hex);path=OUT/f'{tag}.json'
    # broad 연결은 정책 위반 후보도 연결될 수 있게 해, 접속 성공과 배포 적합성의 차이를 보여준다.
    groups={'pqc':'smaug1','broad':'smaug1:X25519','legacy':'X25519'}
    sigs={'pqc':'haetae2','broad':'haetae2:ecdsa_secp256r1_sha256','legacy':'ecdsa_secp256r1_sha256'}
    errors=[]
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(25);port=listener.getsockname()[1]
        def forward():
            try:
                c,_=listener.accept();up=socket.create_connection((ip,4433),timeout=10);up.sendall((route+'\n').encode());up.settimeout(None);relay(c,up)
            except Exception as e:errors.append(str(e))
        th=threading.Thread(target=forward,daemon=True);th.start()
        p=subprocess.run([BIN,'client',groups[client],sigs[client],str(STATE/f'{trust}.crt'),'-','127.0.0.1',str(port),str(path),'1','kpqc-lab.internal'],capture_output=True,timeout=30)
        th.join(timeout=2)
    (OUT/f'{tag}.stderr').write_bytes(p.stderr)
    r=read(path) if path.exists() else {'success':False}
    r.update(returncode=p.returncode,client=client,route=route,trust=trust,tag=tag)
    r['policy_failure']=check(r);save(path,r)
    if errors:r['transport_errors']=errors
    return r
# 접속을 마칠 때마다 0.2초 쉬고 다시 검사한다. 고정 주기의 부하 시험이나 동시 접속 시험은 아니다.
def monitor(ip):
    n=0
    while not (STATE/'monitor.stop').exists():
        r=probe(ip,'active','pqc',tag=f'monitor-{n:04}');r['time_ns']=time.time_ns()
        with open(OUT/'monitor.jsonl','a') as f:f.write(json.dumps(r)+'\n')
        n+=1;time.sleep(.2)
    (STATE/'monitor.done').write_text(str(n))
def main(q):
    STATE.mkdir(exist_ok=True);OUT.mkdir(exist_ok=True)
    action=q['action']
    # 기존 서비스와 후보의 인증서를 따로 만든다. 자체 서명 인증서를 명시적으로 신뢰하는 실험 PKI다.
    if action=='init-server':
        trust={}
        for name,sig in [('active-v1','haetae2'),('good-v2','haetae2'),('wrong-kem','haetae2'),('wrong-signature','EC')]:
            args=['openssl','req','-provider','default','-provider','oqsprovider','-x509','-newkey']
            args+=['ec','-pkeyopt','ec_paramgen_curve:P-256'] if sig=='EC' else [sig]
            # Distinct self-signed issuers avoid ambiguous trust-anchor lookup.
            # The verified service identity remains the same SAN in every cert.
            # SAN은 모두 같은 서비스 이름으로 유지하고 CN은 구분해 자체 서명 신뢰 앵커 선택 충돌을 피한다.
            args+=['-nodes','-keyout',str(STATE/f'{name}.key'),'-out',str(STATE/f'{name}.crt'),'-days','1','-subj',f'/CN={name}','-addext','subjectAltName=DNS:kpqc-lab.internal']
            subprocess.run(args,capture_output=True,check=True,timeout=60);trust[name]=(STATE/f'{name}.crt').read_text()
        pid=launch('active-v1','smaug1','haetae2',24430)
        save(STATE/'processes.json',{'active':pid});save(STATE/'route.json',{'active':{'version':'active-v1','port':24430},'candidate':None})
        log=open(OUT/'router.stderr','wb');p=subprocess.Popen([sys.executable,__file__,'router'],stdout=log,stderr=log,start_new_session=True);log.close()
        procs=read(STATE/'processes.json');procs['router']=p.pid;save(STATE/'processes.json',procs)
        for _ in range(300):
            if (STATE/'router.ready').exists():break
            assert p.poll() is None;time.sleep(.01)
        else:raise RuntimeError('router not ready')
        save(OUT/'public-trust.json',trust);save(OUT/'policy.json',POLICY)
        fingerprints={name:hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() for name,pem in trust.items()}
        return {'trust':trust,'certificate_sha256':fingerprints,'policy':POLICY,'environment':handshake_worker.aws_worker.environment(),'route':read(STATE/'route.json')}
    if action=='init-client':
        for name,pem in q['trust'].items():(STATE/f'{name}.crt').write_text(pem)
        (STATE/'all.crt').write_text(''.join(q['trust'].values()));return {'ready':True,'environment':handshake_worker.aws_worker.environment()}
    # 활성 서비스는 둔 채 별도 후보 포트에만 새 구성을 띄운다.
    if action=='candidate':
        state=read(STATE/'route.json');procs=read(STATE/'processes.json')
        if procs.get('candidate'):
            stop(procs.pop('candidate'));wait_listen(24431)
        state['candidate']=None;save(STATE/'route.json',state)
        name=q['name']
        # 없는 모듈 경로를 지정해 실제 Provider 로딩 실패를 유발한다. 이 경우 TLS 접속 전 사전 검사에서 차단한다.
        if name=='missing-provider':
            env=dict(os.environ,OPENSSL_MODULES='/state/nonexistent-modules')
            p=subprocess.run(['openssl','list','-provider','oqsprovider','-providers'],env=env,capture_output=True)
            (OUT/'missing-provider.stderr').write_bytes(p.stderr)
            assert p.returncode!=0 and b'oqsprovider' in p.stderr
            save(STATE/'processes.json',procs)
            return {'ready':False,'reason':'PROVIDER_UNAVAILABLE','returncode':p.returncode}
        group,sig={'wrong-kem':('X25519','haetae2'),'wrong-signature':('smaug1','EC'),'good-v2':('smaug1','haetae2')}[name]
        Path(str(OUT/name)+'.ready').unlink(missing_ok=True)
        procs['candidate']=launch(name,group,sig,24431);save(STATE/'processes.json',procs)
        state['candidate']={'version':name,'port':24431};save(STATE/'route.json',state)
        return {'ready':True,'route':state}
    if action=='probe':return probe(q['ip'],q.get('route','candidate'),q.get('client','broad'),q.get('trust','all'),q.get('tag'))
    # 신뢰하는 제어 코드가 전달한 접속 증적으로 판정을 다시 계산한다. 서명된 원격 증명 시스템은 아니다.
    if action=='decision':
        # Independently recompute policy from supplied probe evidence; caller is trusted controller.
        probes=q['probes'];reasons=[]
        if not q['ready']:reasons.append(q['startup_reason'])
        else:
            for client in ['broad','pqc']:
                reason=check(probes[client])
                if reason:reasons.append(reason)
            if 'legacy' in q['required_clients'] and not probes['legacy']['success']:reasons.append('REQUIRED_CLIENT_INCOMPATIBLE')
        return {'deployment_allowed':not reasons,'reasons':list(dict.fromkeys(reasons)),'required_clients':q['required_clients'],'policy_version':POLICY['version']}
    # 승인 조건을 재확인하고 active 포인터를 교체한다. 이미 연결된 TCP 세션을 강제로 옮기지는 않는다.
    if action=='promote':
        decision=main({'action':'decision',**q['evidence']});assert decision['deployment_allowed'],'gate did not approve'
        state=read(STATE/'route.json');assert state['candidate']['version']==q['candidate']=='good-v2'
        old=state['active'];state['active']=state['candidate'];state['candidate']=None;save(STATE/'route.json',state)
        save(OUT/'promotion.json',{'before':old,'after':state['active'],'decision':decision,'time_ns':time.time_ns()});return state
    if action=='state':return read(STATE/'route.json')
    # 거절된 후보만 종료하고 후보 경로를 지운다. 기존 활성 서비스의 경로는 유지한다.
    if action=='discard':
        state=read(STATE/'route.json');old=state['candidate'];state['candidate']=None;save(STATE/'route.json',state)
        procs=read(STATE/'processes.json')
        if procs.get('candidate'):
            stop(procs.pop('candidate'));wait_listen(24431);save(STATE/'processes.json',procs)
        return {'discarded':old,'active':state['active']}
    if action=='monitor-start':
        log=open(OUT/'monitor.stderr','wb');p=subprocess.Popen([sys.executable,__file__,'monitor',q['ip']],stdout=log,stderr=log,start_new_session=True);log.close();save(STATE/'monitor.pid',p.pid);return {'started':True}
    if action=='monitor-stop':
        (STATE/'monitor.stop').touch()
        for _ in range(300):
            if (STATE/'monitor.done').exists():break
            time.sleep(.1)
        else:raise RuntimeError('monitor stop timeout')
        rows=[json.loads(x) for x in (OUT/'monitor.jsonl').read_text().splitlines()];return {'samples':len(rows),'failed':sum(x['policy_failure'] is not None for x in rows),'rows':rows}
    if action=='cleanup':
        if (STATE/'monitor.pid').exists():stop(read(STATE/'monitor.pid'))
        if (STATE/'processes.json').exists():
            for pid in read(STATE/'processes.json').values():stop(pid)
        return {'cleaned':True}
    raise ValueError(action)
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='router':router()
    elif len(sys.argv)>1 and sys.argv[1]=='monitor':monitor(sys.argv[2])
    else:print(json.dumps(main(json.load(sys.stdin))))
