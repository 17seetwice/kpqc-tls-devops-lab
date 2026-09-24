#!/usr/bin/env python3
"""Bounded network, prefork load and rollout workers for the isolated lab."""
import concurrent.futures,json,os,signal,subprocess,sys,time
from pathlib import Path
import handshake_worker as hw
import gate_worker as gw
S=Path('/state');O=Path('/results')
def command(*args,check=True):
    p=subprocess.run(args,capture_output=True,text=True,timeout=20)
    if check and p.returncode:raise RuntimeError(' '.join(args)+': '+p.stderr)
    return {'code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
def cpu():
    return Path('/sys/fs/cgroup/cpu.stat').read_text()
def main(q):
    S.mkdir(exist_ok=True);O.mkdir(exist_ok=True);a=q['action']
    if a=='network':
        mtu=int(q['mtu']);delay=int(q['delay_ms']);assert mtu in (1500,9001) and delay in (0,5,15)
        command('ip','link','set','dev','eth0','mtu',str(mtu))
        offload=command('ethtool','-K','eth0','tso','off','gso','off','gro','off',check=False)
        command('tc','qdisc','replace','dev','eth0','root','netem','delay',str(delay)+'ms','limit','10000')
        observed=int(Path('/sys/class/net/eth0/mtu').read_text());assert observed==mtu
        features=command('ethtool','-k','eth0')['stdout']
        assert all(name+': off' in features for name in ['tcp-segmentation-offload','generic-segmentation-offload','generic-receive-offload']), 'required offload controls unavailable'
        return {'mtu':observed,'egress_delay_ms':delay,'qdisc':json.loads(command('tc','-j','-s','qdisc','show','dev','eth0')['stdout']),'offload_change':offload,'offload_state':features}
    if a=='cpu':
        pending=json.loads((S/'pending.json').read_text());pid=pending['pid']
        children=Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
        return {'cpu_stat':cpu(),'server_worker_count':len(children)}
    if a=='serve':
        os.environ['KPQC_SERVER_WORKERS']='8'
        return hw.main({'action':'start',**{k:v for k,v in q.items() if k!='action'},'count':1000000})
    if a=='load-start':
        tag=q['tag'];assert tag.replace('-','').replace('_','').isalnum()
        n=int(q['concurrency']);assert 1<=n<=32
        seconds=float(q['seconds']);assert 0<seconds<=120
        start=S/(tag+'.start');stop=S/(tag+'.stop');start.unlink(missing_ok=True);stop.unlink(missing_ok=True)
        procs=[];prefixes=[]
        env=dict(os.environ,KPQC_LOAD_SECONDS=str(seconds),KPQC_START_FILE=str(start),KPQC_STOP_FILE=str(stop))
        if q.get('route'):env['KPQC_ROUTE']=q['route']
        for i in range(n):
            prefix=O/f'{tag}-client-{i}';prefixes.append(str(prefix))
            log=open(str(prefix)+'.stderr','wb')
            p=subprocess.Popen([hw.BIN,'client',q['kem'],hw.sigalg(q['signature']),str(S/(q.get('trust',q['signature'])+'.crt')),'-',q['ip'],'4433',str(prefix),'1000000','kpqc-lab.internal'],env=env,stdout=log,stderr=log,start_new_session=True);log.close();procs.append(p)
        (S/'load-state.json').write_text(json.dumps({'pids':[p.pid for p in procs],'prefixes':prefixes,'stop':str(stop),'tag':tag}))
        for _ in range(1000):
            if all(Path(p+'.ready').exists() for p in prefixes):break
            assert all(p.poll() is None for p in procs),'load client initialization failed';time.sleep(.01)
        else:raise RuntimeError('load readiness timeout')
        state=json.loads((S/'load-state.json').read_text());state.update(start_ns=time.monotonic_ns(),cpu_before=cpu(),seconds=seconds);(S/'load-state.json').write_text(json.dumps(state));start.touch()
        # A supervisor reaps the clients and stores exit status; current action stays
        # alive only in async subprocess, so direct callers use load-launch below.
        codes=[p.wait(timeout=seconds+30) for p in procs]
        state.update(end_ns=time.monotonic_ns(),cpu_after=cpu(),returncodes=codes)
        (S/'load-done.json').write_text(json.dumps(state));return state
    if a=='load-launch':
        (S/'load-done.json').unlink(missing_ok=True);(S/'load-state.json').unlink(missing_ok=True)
        log=open(O/(q['tag']+'-supervisor.stderr'),'wb')
        p=subprocess.Popen([sys.executable,__file__],stdin=subprocess.PIPE,stdout=log,stderr=log,start_new_session=True)
        p.stdin.write(json.dumps({**q,'action':'load-start'}).encode());p.stdin.close();log.close()
        (S/'load-supervisor.pid').write_text(str(p.pid))
        for _ in range(1000):
            if (S/'load-state.json').exists():
                try:
                    r=json.loads((S/'load-state.json').read_text())
                    if 'start_ns' in r:return {'started':True,'start_ns':r['start_ns']}
                except ValueError:pass
            assert p.poll() is None,(O/(q['tag']+'-supervisor.stderr')).read_text()[-2000:];time.sleep(.01)
        raise RuntimeError('load launch timeout')
    if a=='load-progress':
        state=json.loads((S/'load-state.json').read_text());rows=[]
        for pre in state['prefixes']:
            f=Path(pre+'.jsonl')
            if f.exists():
                for line in f.read_text().splitlines():
                    try:rows.append(json.loads(line))
                    except ValueError:pass
        return {'samples':len(rows),'fingerprints':sorted({r['peer_certificate_sha256'] for r in rows}),'done':(S/'load-done.json').exists()}
    if a=='load-collect':
        state=json.loads((S/'load-state.json').read_text())
        if q.get('stop'):Path(state['stop']).touch()
        for _ in range(1500):
            if (S/'load-done.json').exists():break
            time.sleep(.1)
        else:raise RuntimeError('load collect timeout')
        state=json.loads((S/'load-done.json').read_text());rows=[]
        for i,pre in enumerate(state['prefixes']):
            for line in Path(pre+'.jsonl').read_text().splitlines():rows.append({'worker':i,**json.loads(line)})
            Path(pre+'.jsonl').unlink()
        return {k:v for k,v in state.items() if k not in ('pids','prefixes','stop')}|{'rows':rows,'elapsed_seconds':(state['end_ns']-state['start_ns'])/1e9}
    if a=='gate':
        os.environ['KPQC_SERVER_WORKERS']='8'
        return gw.main(q['request'])
    if a=='cleanup':
        if (S/'load-state.json').exists():
            st=json.loads((S/'load-state.json').read_text());Path(st['stop']).touch()
            for pid in st['pids']:gw.stop(pid)
        if (S/'load-supervisor.pid').exists():gw.stop(int((S/'load-supervisor.pid').read_text()))
        hw.main({'action':'cleanup'});gw.main({'action':'cleanup'});gw.wait_listen(4433)
        for f in O.glob('*-worker-*.jsonl'):f.unlink()
        return {'cleaned':True}
    return hw.main(q)
if __name__=='__main__':print(json.dumps(main(json.load(sys.stdin))))
