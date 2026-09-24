#!/usr/bin/env python3
"""Fresh-process, TLS-only workers. Setup/readiness preface is outside timer."""
import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
import aws_worker

# 순수 TLS 측정용 C 프로그램을 준비·호출·수집한다. HTTP 파일 전송 실험인 aws_worker와 구분한다.
STATE=Path('/state'); OUT=Path('/results'); BIN='/app/tls_handshake'
SIGS=['EC','haetae2','haetae3','haetae5','aimer128f','aimer192f','aimer256f']
CODES=aws_worker.CODES
def run(args):return subprocess.run(list(map(str,args)),capture_output=True,check=True,timeout=60)
def sigalg(s):return 'ecdsa_secp256r1_sha256' if s=='EC' else s
def main(q):
    STATE.mkdir(exist_ok=True);OUT.mkdir(exist_ok=True)
    action=q['action']
    # 서명 알고리즘마다 TLS 서버 인증서와 개인키를 만든다. 키 생성 시간은 핸드셰이크 측정에서 제외한다.
    if action=='init-server':
        trust={}
        for s in SIGS:
            args=['openssl','req','-provider','default','-provider','oqsprovider','-x509','-newkey']
            args+=['ec','-pkeyopt','ec_paramgen_curve:P-256'] if s=='EC' else [s]
            args+=['-nodes','-keyout',STATE/f'{s}.key','-out',STATE/f'{s}.crt','-days','1','-subj','/CN=kpqc-lab.internal','-addext','subjectAltName=DNS:kpqc-lab.internal']
            run(args);trust[s]=(STATE/f'{s}.crt').read_text()
        (OUT/'public-trust.json').write_text(json.dumps(trust,indent=2))
        return {'trust':trust,'environment':aws_worker.environment()}
    if action=='init-client':
        for s,pem in q['trust'].items():
            assert s in SIGS;(STATE/f'{s}.crt').write_text(pem)
        return {'environment':aws_worker.environment()}
    # 이 프로파일의 KEM·TLS 인증 서명을 지정한다. count만큼 연결을 받되 서버는 연결마다 자식을 생성한다.
    if action=='start':
        k,s=q['kem'],q['signature'];assert k in CODES and s in SIGS
        tag=q['tag'];assert tag.replace('-','').replace('_','').isalnum()
        output=OUT/tag;log=open(OUT/f'{tag}.stderr','wb')
        args=[BIN,'server',k,sigalg(s),str(STATE/f'{s}.crt'),str(STATE/f'{s}.key'),'0.0.0.0','4433',str(output),str(q['count']),'kpqc-lab.internal']
        env=dict(os.environ)
        if q.get('warm'):env['KPQC_WARM']='1'
        if q.get('memory'):env['KPQC_MEMORY']='1'
        p=subprocess.Popen(args,stdout=log,stderr=log,start_new_session=True,env=env);log.close()
        (STATE/'pending.json').write_text(json.dumps({'tag':tag,'pid':p.pid,'count':q['count']}))
        for _ in range(200):
            if Path(str(output)+'.ready').exists():return {'ready':True}
            assert p.poll() is None,'server exited';time.sleep(.01)
        raise RuntimeError('server readiness timeout')
    # 반복마다 새로운 C 클라이언트 프로세스를 실행해 세션 재사용 없는 핸드셰이크를 측정한다.
    if action=='clients':
        k,s=q['kem'],q['signature'];tag=q['tag'];rows=[]
        env=dict(os.environ)
        if q.get('memory'):env['KPQC_MEMORY']='1'
        if q.get('warm'):
            env['KPQC_WARM']='1'
            prefix=OUT/tag
            p=subprocess.run([BIN,'client',k,sigalg(s),str(STATE/f'{s}.crt'),'-',q['ip'],'4433',str(prefix),str(q['count']),q.get('host','kpqc-lab.internal')],capture_output=True,timeout=120,env=env)
            (OUT/f'{tag}.stderr').write_bytes(p.stderr)
            for i in range(q['count']):
                row=json.loads((OUT/f'{tag}-{i:03d}.json').read_text());row['returncode']=p.returncode;rows.append(row)
            return {'rows':rows}
        for i in range(q['count']):
            path=OUT/f'{tag}-{i:03d}.json'
            p=subprocess.run([BIN,'client',q.get('client_kem',k),sigalg(q.get('client_signature',s)),str(STATE/f'{q.get("trust_signature",s)}.crt'),'-',q['ip'],'4433',str(path),'1',q.get('host','kpqc-lab.internal')],capture_output=True,timeout=25,env=env)
            (OUT/f'{tag}-{i:03d}.stderr').write_bytes(p.stderr)
            assert path.exists(),p.stderr.decode()
            row=json.loads(path.read_text());row['returncode']=p.returncode
            rows.append(row)
        return {'rows':rows}
    # 서버 측 결과까지 모으고 포트가 닫힐 때까지 기다린 뒤 다음 프로파일로 넘어간다.
    if action=='collect':
        pending=json.loads((STATE/'pending.json').read_text());assert pending['tag']==q['tag']
        paths=[OUT/f'{pending["tag"]}-{i:03d}.json' for i in range(pending['count'])]
        for _ in range(500):
            if all(p.exists() for p in paths):
                try:rows=[json.loads(p.read_text()) for p in paths];break
                except json.JSONDecodeError:pass
            time.sleep(.01)
        else:raise RuntimeError('server results timeout')
        # Wait for listen socket to close before the next profile binds.
        for _ in range(500):
            if not any(r.split()[1]=='00000000:1151' and r.split()[3]=='0A' for r in Path('/proc/net/tcp').read_text().splitlines()[1:]):break
            time.sleep(.01)
        else:raise RuntimeError('server still listening')
        (STATE/'pending.json').unlink();return {'rows':rows}
    if action=='memory-selftest':
        return json.loads(run([BIN,'memory-selftest']).stdout)
    if action=='metadata':
        return {'kernel':os.uname().release,'mtu':{p.parent.name:p.read_text().strip() for p in Path('/sys/class/net').glob('*/mtu')},'cpu_stat':Path('/proc/stat').read_text().splitlines()[0], 'cpuinfo':Path('/proc/cpuinfo').read_text().split('\n\n')[0],'environment':aws_worker.environment()}
    if action=='cleanup':
        p=STATE/'pending.json'
        if p.exists():
            try:os.killpg(json.loads(p.read_text())['pid'],signal.SIGTERM)
            except ProcessLookupError:pass
            p.unlink()
        return {'cleaned':True}
    raise ValueError(action)
if __name__=='__main__':print(json.dumps(main(json.load(sys.stdin))))
