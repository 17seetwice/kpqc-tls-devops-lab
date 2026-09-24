#!/usr/bin/env python3
"""A worker on ONE EC2. Only public trust material crosses the control channel."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time
import lab

STATE=Path('/state')
OUT=Path('/results')
HOST='kpqc-lab.internal'
CODES={'X25519':29,'smaug1':65056,'smaug3':65059,'smaug5':65062,
       'ntruplus_kem576':65064,'ntruplus_kem768':65067,'ntruplus_kem864':65070,'ntruplus_kem1152':65073}

def measured(args,path):
    return ['/app/measure',str(path),*map(str,args)]
lab.measured_command=measured

def resources(path):
    r=json.loads(path.read_text())
    r['total_cpu_ms']=round(r['user_cpu_ms']+r['system_cpu_ms'],3)
    r['cpu_output_unit_ms']=.001
    return r

def instance():
    obj=lab.Lab.__new__(lab.Lab)
    obj.work,obj.out=STATE,OUT
    obj.public,obj.keys,obj.logs=STATE/'public',STATE/'keys',OUT/'logs'
    for p in (obj.public,obj.keys,obj.logs):p.mkdir(parents=True,exist_ok=True)
    obj.trust={a:obj.keys/f'{a}.pub.pem' for a in lab.ALGORITHMS}
    obj.seen=set()
    return obj

def environment():
    return {'platform':platform.platform(),'machine':platform.machine(),
       'openssl':lab.run(['openssl','version']).stdout.decode().strip(),
       'providers':lab.ssl('list','-providers').stdout.decode(),
       'base_digest':lab.BASE_DIGEST,'library_metadata':lab.library_metadata(),
       'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/app/scripts').glob('*') if p.is_file()},
       'schema_sha256':hashlib.sha256(lab.SCHEMA.read_bytes()).hexdigest(),
       'cpu_max':Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
       'memory_max':Path('/sys/fs/cgroup/memory.max').read_text().strip()}

def main(q):
    obj=instance()
    action=q['action']
    if action=='init-server':
        assert not (STATE/'initialized').exists(),'already initialized'
        for a in lab.ALGORITHMS:obj.keygen(a)
        lab.ssl('req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes',
          '-keyout',obj.keys/'tls.pem','-out',STATE/'tls.crt','-days','1','-subj',f'/CN={HOST}',
          '-addext',f'subjectAltName=DNS:{HOST},IP:{q["server_ip"]}')
        trust={'certificate':(STATE/'tls.crt').read_text(),'public_keys':{a:p.read_text() for a,p in obj.trust.items()}}
        (OUT/'public-trust.json').write_text(json.dumps(trust,indent=2))
        (OUT/'statement.xml').write_bytes(lab.statement())
        (STATE/'initialized').write_text('sender')
        return {'trust':trust,'environment':environment()}
    if action=='init-client':
        assert not (STATE/'initialized').exists(),'already initialized'
        (STATE/'tls.crt').write_text(q['trust']['certificate'])
        for a in lab.ALGORITHMS:obj.trust[a].write_text(q['trust']['public_keys'][a])
        (STATE/'initialized').write_text('receiver')
        return {'environment':environment()}
    if action=='prepare':
        assert q['kem'] in CODES and q['signature'] in lab.ALGORITHMS
        assert not (STATE/'pending.json').exists(),'previous session not collected'
        sid=q['session_id']; assert sid.replace('-','').replace('_','').isalnum()
        rp=obj.logs/f'{sid}-sign.json'
        bundle,ms,size=obj.sign(q['signature'],lab.statement(),resource_path=rp)
        payload=json.dumps(bundle).encode()
        (obj.public/'bundle.json').write_bytes(payload)
        sp=obj.logs/f'{sid}-server.json'
        log=open(obj.logs/f'{sid}-server.log','wb')
        cmd=['openssl','s_server','-provider','default','-provider','oqsprovider',
          '-accept','0.0.0.0:4433','-cert',str(STATE/'tls.crt'),'-key',str(obj.keys/'tls.pem'),
          '-groups',q['kem'],'-tls1_3','-ciphersuites','TLS_AES_256_GCM_SHA384','-WWW','-quiet','-naccept','1']
        start=time.perf_counter()
        proc=subprocess.Popen(measured(cmd,sp),cwd=obj.public,stdout=log,stderr=log,start_new_session=True)
        log.close()
        (STATE/'pending.json').write_text(json.dumps({'session_id':sid,'pid':proc.pid}))
        for _ in range(150):
            if proc.poll() is not None:raise RuntimeError('TLS server exited before listen')
            if any(r.split()[1]=='00000000:1151' and r.split()[3]=='0A' for r in Path('/proc/net/tcp').read_text().splitlines()[1:]):break
            time.sleep(.01)
        else:raise RuntimeError('listen timeout')
        return {'session_id':sid,'sign_process_ms':ms,'sign':resources(rp),'signature_bytes':size,
          'envelope_bytes':len(payload),'envelope_sha256':hashlib.sha256(payload).hexdigest(),
          'server_start_to_ready_ms':round((time.perf_counter()-start)*1000,3)}
    if action=='collect':
        pending=json.loads((STATE/'pending.json').read_text()); sid=pending['session_id']
        assert q['session_id']==sid
        sp=obj.logs/f'{sid}-server.json'
        for _ in range(300):
            if sp.exists():
                try:r=resources(sp);break
                except json.JSONDecodeError:pass
            time.sleep(.01)
        else:
            os.killpg(pending['pid'],signal.SIGTERM)
            raise RuntimeError('server did not finish')
        (STATE/'pending.json').unlink()
        return {'server':r}
    if action=='receive':
        sid=q['session_id']; assert sid.replace('-','').replace('_','').isalnum()
        trace=obj.logs/f'{sid}.trace'; rp=obj.logs/f'{sid}-client.json'
        args=['openssl','s_client','-provider','default','-provider','oqsprovider',
          '-connect',f'{q["server_ip"]}:4433','-servername',HOST,'-verify_hostname',q.get('hostname',HOST),
          '-verify_return_error','-CAfile',str(STATE/'tls.crt'),'-groups',q['kem'],'-tls1_3',
          '-ciphersuites','TLS_AES_256_GCM_SHA384','-brief','-ign_eof','-trace','-msgfile',str(trace)]
        start=time.perf_counter()
        p=lab.run(measured(args,rp),data=b'GET /bundle.json HTTP/1.0\r\nHost: kpqc-lab.internal\r\n\r\n',check=False)
        client_ms=(time.perf_counter()-start)*1000
        stderr=p.stderr.decode(errors='replace');(obj.logs/f'{sid}.stderr').write_text(stderr)
        if q.get('expect_rejection'):
            assert p.returncode!=0,'negative TLS check unexpectedly accepted'
            return {'rejected':True,'client':resources(rp)}
        assert p.returncode==0 and 'Verification: OK' in stderr and p.stdout.startswith(b'HTTP/1.0 200'),stderr
        payload=p.stdout.split(b'\r\n\r\n',1)[1]
        assert hashlib.sha256(payload).hexdigest()==q['envelope_sha256'],'download bytes mismatch'
        text=trace.read_text(); hello=text.split('ServerHello,',1)[-1].split('Received Record',1)[0]
        import re
        match=re.search(r'(?:NamedGroup|named_group):\s*([^\n]+)',hello)
        assert match and f'({CODES[q["kem"]]})' in match.group(1),'unexpected negotiated group'
        bundle=json.loads(payload); paths={s:obj.logs/f'{sid}-{s}.json' for s in ('verify','xml')}
        verify_start=time.perf_counter()
        validated=obj.receive(bundle,{q['signature']},resource_paths=paths)
        verify_ms=(time.perf_counter()-verify_start)*1000
        assert validated['entries']==3
        return {'passed':True,'server_group_trace':match.group(1),'client_process_ms':round(client_ms,3),
          'verify_plus_xml_wall_ms':round(verify_ms,3),'client':resources(rp),
          'verify':resources(paths['verify']),'xml':resources(paths['xml'])}
    if action=='cleanup':
        p=STATE/'pending.json'
        if p.exists():
            try:os.killpg(json.loads(p.read_text())['pid'],signal.SIGTERM)
            except ProcessLookupError:pass
            p.unlink()
        return {'cleaned':True}
    raise ValueError(action)

if __name__=='__main__':
    os.umask(0o077)
    print(json.dumps(main(json.load(sys.stdin))))
