#!/usr/bin/env python3
"""Lab migration admission and recovery; fixed arrivals with all attempts retained."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import gate_worker as gw
import release_policy

S=Path('/state');O=Path('/results')
P=json.loads(Path('/app/policies/release-slo.json').read_text())
if os.getenv('KPQC_RELEASE_SMOKE')=='1':P.update(window_seconds=2,required_windows=1)
POLICY_HASH=hashlib.sha256(json.dumps(P,sort_keys=True).encode()).hexdigest()


def attempt(ip,route,tag,sequence,scheduled_ns):
    start=time.monotonic_ns();path=O/f'{tag}-{sequence}.json'
    env=dict(os.environ,KPQC_ROUTE=route)
    row={'sequence':sequence,'scheduled_ns':scheduled_ns,'started_ns':start,'generator_lateness_ms':max(0,(start-scheduled_ns)/1e6)}
    try:
        p=subprocess.run([gw.BIN,'client','smaug1:X25519','haetae2:ecdsa_secp256r1_sha256',str(S/'all.crt'),'-',ip,'4433',str(path),'1','kpqc-lab.internal'],capture_output=True,timeout=P['attempt_timeout_seconds'],env=env)
        tls=json.loads(path.read_text()) if path.exists() else {}
        row.update(returncode=p.returncode,tls=tls,ok=p.returncode==0 and tls.get('success') is True and tls.get('verify_result')==0,
                   error=None if p.returncode==0 else ('tls-failure' if tls else 'transport-or-client-failure'))
    except subprocess.TimeoutExpired:row.update(ok=False,error='attempt-timeout',returncode=124,tls={})
    except (ValueError,OSError):row.update(ok=False,error='invalid-or-missing-client-record',returncode=125,tls={})
    row['ended_ns']=time.monotonic_ns();row['admission_ms']=(row['ended_ns']-scheduled_ns)/1e6
    path.unlink(missing_ok=True)
    return row


def window(q):
    tag='arrival-'+uuid.uuid4().hex;rate=P['arrival_rate_per_second'];seconds=q.get('seconds',P['window_seconds'])
    assert 0<seconds<=30
    total=round(rate*seconds);start=time.monotonic_ns()+100_000_000;futures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        for i in range(total):
            planned=start+round(i*1e9/rate)
            time.sleep(max(0,(planned-time.monotonic_ns())/1e9))
            futures.append(pool.submit(attempt,q['ip'],q.get('route','candidate'),tag,i,planned))
        rows=[f.result() for f in futures]
    return {'tag':tag,'rate':rate,'seconds':seconds,'start_ns':start,'end_ns':time.monotonic_ns(),'observed_at_ns':time.time_ns(),'rows':rows}


def decision(q):
    crypto=gw.main({'action':'decision',**q['evidence']})
    candidate=gw.read(S/'route.json')['candidate']
    perf=release_policy.evaluate(q.get('performance'),P,candidate)
    return {'deployment_allowed':crypto['deployment_allowed'] and perf['passed'],'crypto':crypto,'performance':perf,'release_policy_sha256':POLICY_HASH}


def main(q):
    S.mkdir(exist_ok=True);O.mkdir(exist_ok=True);os.environ['KPQC_SERVER_WORKERS']='8'
    action=q['action']
    if action=='init-server':
        result=gw.main({'action':'init-server','initial_legacy':True});result['release_policy']=P;result['release_policy_sha256']=POLICY_HASH
        return result
    if action=='policy':return {'policy':P,'policy_sha256':POLICY_HASH}
    if action=='window':return window(q)
    if action=='window-launch':
        tag='background-'+uuid.uuid4().hex
        log=open(O/(tag+'.stderr'),'wb')
        proc=subprocess.Popen([sys.executable,__file__,'--background',tag],stdin=subprocess.PIPE,stdout=log,stderr=log,start_new_session=True)
        proc.stdin.write(json.dumps(q).encode());proc.stdin.close();log.close()
        gw.save(S/'background.json',{'tag':tag,'pid':proc.pid})
        return {'started':True,'tag':tag}
    if action=='window-collect':
        state=gw.read(S/'background.json');path=O/(state['tag']+'.json')
        for _ in range(400):
            if path.exists():return gw.read(path)
            time.sleep(.1)
        raise RuntimeError('background arrival collector did not finish')
    if action=='health':return attempt(q['ip'],q.get('route','active'),'health-'+uuid.uuid4().hex,0,time.monotonic_ns())
    if action=='decision':return decision(q)
    if action=='promote':
        verdict=decision(q)
        if not verdict['deployment_allowed']:raise ValueError('release rejected')
        before=gw.read(S/'route.json');pid=gw.read(S/'processes.json')['active']
        result=gw.main({'action':'promote','candidate':q['candidate'],'evidence':q['evidence']})
        # The former service remains live; only an approved PQC version may be restored.
        gw.save(S/'rollback.json',{'route':before['active'],'pid':pid,'approved':before['active'].get('release_approved') is True,
                                 'release_policy_sha256':POLICY_HASH})
        result['rollback']=before['active'] if before['active'].get('release_approved') is True else None
        result['active']['release_approved']=True
        result['active']['release_policy_sha256']=POLICY_HASH
        gw.save(S/'route.json',result);gw.save(O/('release-'+q['candidate']+'.json'),verdict)
        return result
    if action=='fault-active':
        before=gw.read(S/'route.json');gw.stop(gw.read(S/'processes.json')['active'])
        return {'injected':'active-process-group-termination','version':before['active']['version'],'observed_at_ns':time.time_ns()}
    if action=='rollback':
        old=gw.read(S/'rollback.json');state=gw.read(S/'route.json')
        if not old['approved'] or old['release_policy_sha256']!=POLICY_HASH:
            return {'restored':False,'reason':'NO_APPROVED_PQC_ROLLBACK_TARGET','active':state['active']}
        r=q.get('health',{});tls=r.get('tls',{})
        if not r.get('ok') or gw.check({**tls,'returncode':r.get('returncode')}) is not None or tls.get('peer_certificate_sha256')!=old['route']['certificate_sha256']:
            return {'restored':False,'reason':'ROLLBACK_TARGET_NOT_HEALTHY','active':state['active']}
        # Health is created by the trusted controller immediately before this request.
        observed=q.get('health_observed_at_ns',0)
        if not 0<=time.time_ns()-observed<=5_000_000_000:return {'restored':False,'reason':'STALE_ROLLBACK_HEALTH'}
        previous=state['active'];state['active']=old['route'];state['rollback']=None
        procs=gw.read(S/'processes.json');procs['active']=old['pid'];gw.save(S/'processes.json',procs);gw.save(S/'route.json',state)
        event={'restored':True,'before':previous,'after':state['active'],'observed_at_ns':time.time_ns()};gw.save(O/'rollback-event.json',event)
        return event
    if action=='workers':
        p=gw.read(S/'processes.json')['active']
        children=Path(f'/proc/{p}/task/{p}/children').read_text().split()
        return {'active_workers':sum(Path(f'/proc/{x}/stat').read_text().split()[2]!='Z' for x in children)}
    if action=='candidate':
        result=gw.main(q);result['route']['candidate']['release_policy_sha256']=POLICY_HASH;gw.save(S/'route.json',result['route']);return result
    if action=='cleanup' and (S/'background.json').exists():gw.stop(gw.read(S/'background.json')['pid'])
    if action in ['init-client','probe','discard','state','cleanup']:return gw.main(q)
    raise ValueError(action)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--background':gw.save(O/(sys.argv[2]+'.json'),window(json.load(sys.stdin)))
    else:print(json.dumps(main(json.load(sys.stdin))))
