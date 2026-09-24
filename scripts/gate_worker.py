#!/usr/bin/env python3
"""Lab-only deployment worker, TCP control router and sampled active monitor."""
import hashlib,json,os,select,signal,socket,ssl,subprocess,sys,threading,time,uuid
from pathlib import Path
import handshake_worker

STATE=Path('/state');OUT=Path('/results');BIN='/app/tls_handshake'
POLICY=json.loads(Path('/app/policies/pqc-required.json').read_text())
def save(p,v):
    tmp=Path(str(p)+'.'+uuid.uuid4().hex);tmp.write_text(json.dumps(v,indent=2));os.replace(tmp,p)
def check(r):
    if not r or not r.get('success') or r.get('returncode')!=0:return 'TLS_HANDSHAKE_FAILED'
    if r['verify_result']!=0:return 'CERTIFICATE_VERIFICATION_FAILED'
    for key,want,reason in [('tls_version',POLICY['tls_version'],'TLS_VERSION_MISMATCH'),('group_code',POLICY['group_code'],'KEM_POLICY_MISMATCH'),('signature_code',POLICY['signature_code'],'SIGNATURE_POLICY_MISMATCH'),('cipher',POLICY['cipher'],'CIPHER_POLICY_MISMATCH')]:
        if r[key]!=want:return reason
    return None
def read(p):return json.loads(p.read_text())
def stop(pid):
    try:os.killpg(pid,signal.SIGTERM)
    except ProcessLookupError:pass
def wait_listen(port):
    for _ in range(300):
        if not any(x.split()[1].endswith(f':{port:04X}') and x.split()[3]=='0A' for x in Path('/proc/net/tcp').read_text().splitlines()[1:]):return
        time.sleep(.01)
    raise RuntimeError('listener not closed')
def launch(name,group,sig,port):
    prefix=OUT/name;log=open(OUT/f'{name}.stderr','wb')
    p=subprocess.Popen([BIN,'server',group,handshake_worker.sigalg(sig),str(STATE/f'{name}.crt'),str(STATE/f'{name}.key'),'127.0.0.1',str(port),str(prefix),'10000','kpqc-lab.internal'],stdout=log,stderr=log,start_new_session=True);log.close()
    for _ in range(300):
        if Path(str(prefix)+'.ready').exists():return p.pid
        if p.poll() is not None:raise RuntimeError('server launch failed')
        time.sleep(.01)
    raise RuntimeError('readiness timeout')
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
def router():
    def serve(c):
        try:
            c.settimeout(5);label=b''
            while not label.endswith(b'\n') and len(label)<16:
                b=c.recv(1)
                if not b:raise ValueError('missing selector')
                label+=b
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
def probe(ip,route,client='broad',trust='all',tag=None):
    tag=tag or ('probe-'+uuid.uuid4().hex);path=OUT/f'{tag}.json'
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
    if action=='init-server':
        trust={}
        for name,sig in [('active-v1','haetae2'),('good-v2','haetae2'),('wrong-kem','haetae2'),('wrong-signature','EC')]:
            args=['openssl','req','-provider','default','-provider','oqsprovider','-x509','-newkey']
            args+=['ec','-pkeyopt','ec_paramgen_curve:P-256'] if sig=='EC' else [sig]
            # Distinct self-signed issuers avoid ambiguous trust-anchor lookup.
            # The verified service identity remains the same SAN in every cert.
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
    if action=='candidate':
        state=read(STATE/'route.json');procs=read(STATE/'processes.json')
        if procs.get('candidate'):
            stop(procs.pop('candidate'));wait_listen(24431)
        state['candidate']=None;save(STATE/'route.json',state)
        name=q['name']
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
    if action=='promote':
        decision=main({'action':'decision',**q['evidence']});assert decision['deployment_allowed'],'gate did not approve'
        state=read(STATE/'route.json');assert state['candidate']['version']==q['candidate']=='good-v2'
        old=state['active'];state['active']=state['candidate'];state['candidate']=None;save(STATE/'route.json',state)
        save(OUT/'promotion.json',{'before':old,'after':state['active'],'decision':decision,'time_ns':time.time_ns()});return state
    if action=='state':return read(STATE/'route.json')
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
