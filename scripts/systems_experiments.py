#!/usr/bin/env python3
"""Four bounded follow-up experiments; never modifies the host NIC or SSH path."""
import argparse,json,os,random,shlex,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
p=argparse.ArgumentParser();p.add_argument('--server');p.add_argument('--client');p.add_argument('--server-private');p.add_argument('--image',default='kpqc-lab:gate');p.add_argument('--local',action='store_true');p.add_argument('--smoke',action='store_true');p.add_argument('--rollout-only',action='store_true');a=p.parse_args()
ROOT=Path(__file__).resolve().parents[1];RUN=datetime.now(timezone.utc).strftime(('local' if a.local else 'aws')+'-systems-%Y%m%dT%H%M%SZ');OUT=ROOT/'artifacts'/RUN;OUT.mkdir(parents=True)
HOSTS={'server':a.server,'client':a.client};started=[];networks=[]
D={'run_id':RUN,'status':'running','suite':'rollout-only' if a.rollout_only else 'full','source_commit':os.getenv('GITHUB_SHA'),'image_identity':os.getenv('KPQC_IMAGE_ID','local-unattested'),'started_at':datetime.now(timezone.utc).isoformat(),'network':[],'hrr':[],'throughput':[],'rollout':[],'assertions':[],'measurement':{'network':'isolated Docker bridge; eth0 MTU 1500/9001; netem egress delay 0/5/15 ms on both endpoints; not an Internet/WAN measurement','latency':'SSL_connect; one warm process/context per condition, first two full handshakes excluded','load':'closed-loop clients, eight prefork server workers; full TLS handshakes; finite-window instrumented service throughput includes TCP, readiness, TLS, teardown and record writing','rollout':'four concurrent closed-loop clients through the TCP router; reject mixed-KEM candidate, then promote approved candidate; verify peer certificate fingerprints','scope':'five representative profiles; one EC2 pair; three within-run blocks, not independent deployment replications'}}
saved_parts={}
def save(final=False):
    # Persist each completed block once; rewriting all previous load rows at each
    # assertion delayed the controller and polluted the transition experiment.
    parts=OUT/'records';parts.mkdir(exist_ok=True)
    for section in ['network','hrr','throughput','rollout']:
        start=saved_parts.get(section,0)
        for i in range(start,len(D[section])):
            (parts/f'{section}-{i:03d}.json').write_text(json.dumps(D[section][i]))
        saved_parts[section]=len(D[section])
    content=D if final else {'run_id':RUN,'status':D['status'],'completed':saved_parts,'last_assertion':D['assertions'][-1:]}
    path=OUT/('results.json' if final else 'progress.json');tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(content));os.replace(tmp,path)
def check(name,ok):
    D['assertions'].append({'name':name,'passed':bool(ok)});save();assert ok,name

def cmd(role,command,data=None,timeout=240):
    if a.local:argv=['sh','-c',command.replace('sudo docker','docker')]
    else:argv=['ssh','-i',str(ROOT/'kpqc-devops-lab.pem'),'-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlias=kpqc-'+role,'-o',f'UserKnownHostsFile={ROOT}/.aws-runtime/known_hosts','-o','ControlMaster=auto','-o','ControlPersist=600','-o',f'ControlPath={ROOT}/.aws-runtime/sys-%h','ubuntu@'+HOSTS[role],command]
    r=subprocess.run(argv,input=data,capture_output=True,timeout=timeout)
    if r.returncode:raise RuntimeError(role+': '+r.stderr.decode(errors='replace')[-2000:])
    return r.stdout

def worker(role,q):return json.loads(cmd(role,f'sudo docker exec -i kpqc-systems-{role} python3 /app/scripts/systems_worker.py',json.dumps(q).encode()))
def gate(role,q):return worker(role,{'action':'gate','request':q})
CODES={'X25519':29,'smaug1':65056,'ntruplus_kem768':65067};SIGS={'EC':1027,'haetae2':65408,'aimer128f':65411}
profiles=[('X25519','EC')]+[(k,s) for k in ['smaug1','ntruplus_kem768'] for s in ['haetae2','aimer128f']]
if a.smoke:profiles=[('X25519','EC'),('smaug1','haetae2'),('ntruplus_kem768','aimer128f')]
def validate(rows,k,s,hrr=0):
    return bool(rows) and all(r['success'] and r['verify_result']==0 and not r['reused'] and r['tls_version']=='TLSv1.3' and r['cipher']=='TLS_AES_256_GCM_SHA384' and r['group_code']==CODES[k] and r['signature_code']==SIGS[s] and r['hello_retry_requests']==hrr for r in rows)
def setnet(mtu,delay):return {r:worker(r,{'action':'network','mtu':mtu,'delay_ms':delay}) for r in HOSTS}
def session(k,s,tag,retry=False):
    q={'kem':k,'signature':s,'tag':tag,'count':5,'warm':True}
    worker('server',{'action':'start',**q,'tag':tag+'-s'})
    cs=worker('client',{'action':'clients',**q,'client_kem':('X25519:'+k) if retry else k,'ip':IP})['rows']
    ss=worker('server',{'action':'collect','tag':tag+'-s'})['rows']
    D['pending_sessions']={'tag':tag,'client':cs,'server':ss};save()
    check(tag+'-tls',len(cs)==len(ss)==5 and validate(cs,k,s,int(retry)) and validate(ss,k,s,int(retry)))
    check(tag+'-bytes',all(c['sent_handshake_bytes']==t['received_handshake_bytes'] and t['sent_handshake_bytes']==c['received_handshake_bytes'] for c,t in zip(cs,ss)))
    D.pop('pending_sessions',None)
    return [{'warmup':i<2,'client':c,'server':t} for i,(c,t) in enumerate(zip(cs,ss))]
try:
    # Use separate per-role networks locally; on AWS each network is on its own host.
    for role in HOSTS:
        net='kpqc-systems-'+role
        cmd(role,f'sudo docker network create --opt com.docker.network.driver.mtu=9001 {net}');networks.append(role)
        port=' -p 4433:4433' if role=='server' else ''
        cmd(role,f'sudo docker run -d --init --name {net} --network {net}{port} --cap-add NET_ADMIN --cpus 2 --memory 512m --tmpfs /state:size=64m --tmpfs /results:size=256m -e KPQC_IMAGE_ID={shlex.quote(os.getenv("KPQC_IMAGE_ID","local-unattested"))} {shlex.quote(a.image)}');started.append(role)
    if a.local:
        # eth0 shaping requires traffic on eth0, so use host gateway/published port instead.
        IP=json.loads(cmd('client',"sudo docker network inspect kpqc-systems-client"))[0]['IPAM']['Config'][0]['Gateway']
    else:IP=a.server_private
    if not a.rollout_only:
        trust=worker('server',{'action':'init-server'});worker('client',{'action':'init-client','trust':trust['trust']})
        D['environment']={r:worker(r,{'action':'metadata'}) for r in HOSTS}
        rng=random.Random(20260927);blocks=1 if a.smoke else 3
        for block in range(blocks):
            conditions=[(m,d) for m in [1500,9001] for d in ([0,5] if a.smoke else [0,5,15])];rng.shuffle(conditions)
            for mtu,delay in conditions:
                net=setnet(mtu,delay);order=list(profiles);rng.shuffle(order)
                for k,s in order:
                    tag=f'net-{block}-{mtu}-{delay}-{k}-{s}';rows=session(k,s,tag)
                    check(tag+'-mss',all(r['client']['tcp_snd_mss']<=mtu-40 and r['server']['tcp_snd_mss']<=mtu-40 for r in rows))
                    if mtu==9001:check(tag+'-jumbo-mss',all(r['client']['tcp_snd_mss']>1460 and r['server']['tcp_snd_mss']>1460 for r in rows))
                    if delay:check(tag+'-delay-observed',all(r['client']['tcp_rtt_us']>=delay*1000 for r in rows))
                    D['network'].append({'block':block,'mtu':mtu,'egress_delay_ms':delay,'kem':k,'signature':s,'network_state':net,'sessions':rows});save();print(tag,'PASS',flush=True)
        for block in range(blocks):
            for delay in ([0,5] if a.smoke else [0,5,15]):
                net=setnet(1500,delay)
                for k,s in [p for p in profiles if p[0]!='X25519']:
                    order=[False,True];rng.shuffle(order)
                    for retry in order:
                        tag=f'hrr-{block}-{delay}-{k}-{s}-{int(retry)}';rows=session(k,s,tag,retry)
                        D['hrr'].append({'block':block,'mtu':1500,'egress_delay_ms':delay,'kem':k,'signature':s,'induced_hrr':retry,'sessions':rows});save();print(tag,'PASS',flush=True)
        setnet(1500,0)
        for block in range(blocks):
            order=[(k,s,n) for k,s in profiles for n in ([1,4] if a.smoke else [1,4,16])];rng.shuffle(order)
            for k,s,n in order:
                tag=f'load-{block}-{k}-{s}-{n}'
                worker('server',{'action':'serve','kem':k,'signature':s,'tag':tag})
                # Prime the persistent workers before measuring, retaining these probes separately.
                warm=worker('client',{'action':'clients','kem':k,'signature':s,'tag':tag+'-prime','count':16,'warm':True,'ip':IP})
                check(tag+'-prime',validate(warm['rows'],k,s))
                before=worker('server',{'action':'cpu'})
                worker('client',{'action':'load-launch','kem':k,'signature':s,'tag':tag,'concurrency':n,'seconds':2 if a.smoke else 8,'ip':IP})
                data=worker('client',{'action':'load-collect'});after=worker('server',{'action':'cpu'})
                D['throughput'].append({'block':block,'kem':k,'signature':s,'concurrency':n,'server_workers':8,'priming_sessions':warm['rows'],'server_cpu_before':before,'server_cpu_after':after,'load':data});save()
                check(tag+'-workers',before['server_worker_count']==after['server_worker_count']==8)
                check(tag+'-tls',validate(data['rows'],k,s) and all(x==0 for x in data['returncodes']))
                worker('server',{'action':'cleanup'});print(tag,len(data['rows']),'PASS',flush=True)
    # Release trial: actual existing gate plus simultaneous persistent load clients.
    setnet(1500,0)
    initial=gate('server',{'action':'init-server'});gate('client',{'action':'init-client','trust':initial['trust']})
    D['rollout_certificate_sha256']={n:initial['certificate_sha256'][n] for n in ['active-v1','good-v2','mixed-kem']}
    worker('client',{'action':'load-launch','kem':'smaug1','signature':'haetae2','trust':'all','tag':'rollout','route':'active','concurrency':4,'seconds':120,'ip':IP})
    for _ in range(100):
        progress=worker('client',{'action':'load-progress'})
        if progress['samples']>=20:break
        time.sleep(.1)
    check('rollout-initial-traffic',progress['samples']>=20 and not progress['done'])
    for name in ['mixed-kem','good-v2']:
        before=gate('server',{'action':'state'});candidate=gate('server',{'action':'candidate','name':name})
        probes={c:gate('client',{'action':'probe','ip':IP,'route':'candidate','client':c,'trust':'all','tag':'under-load-'+name+'-'+c}) for c in ['broad','pqc','classical_kem','classical_signature','legacy','tls12']}
        ev={'binding':candidate['route']['candidate'],'ready':True,'probes':probes,'required_clients':['pqc']}
        decision=gate('server',{'action':'decision',**ev});check('under-load-'+name+'-decision',decision['deployment_allowed']==(name=='good-v2'))
        live=worker('client',{'action':'load-progress'})
        check('under-load-'+name+'-traffic',not live['done'] and live['live_workers']==4)
        if name=='good-v2':after=gate('server',{'action':'promote','candidate':name,'evidence':ev})
        else:
            gate('server',{'action':'discard'});after=gate('server',{'action':'state'});check('rejection-keeps-active',before['active']==after['active'])
        D['rollout'].append({'candidate':name,'decision':decision,'probes':probes,'progress':worker('client',{'action':'load-progress'})});save()
    # Require successful traffic to the promoted certificate while workers live.
    for _ in range(30):
        progress=worker('client',{'action':'load-progress'})
        if initial['certificate_sha256']['good-v2'] in progress['fingerprints']:break
        if progress['done']:break
        time.sleep(.1)
    D['post_promotion_progress']=progress
    D['post_promotion_hold_seconds']=1 if a.smoke else 60
    time.sleep(D['post_promotion_hold_seconds'])
    data=worker('client',{'action':'load-collect','stop':True})
    D['rollout_load']=data
    D['endpoint_diagnostics']={r:worker(r,{'action':'diagnostics'}) for r in HOSTS};save()
    allowed={initial['certificate_sha256'][n] for n in ['active-v1','good-v2']};observed={r['peer_certificate_sha256'] for r in data['rows']}
    check('rollout-both-approved-identities',observed==allowed)
    check('rollout-traffic-tls',validate(data['rows'],'smaug1','haetae2') and all(x==0 for x in data['returncodes']))
    D['rollout_load']=data;D['rollout_certificate_sha256']={n:initial['certificate_sha256'][n] for n in ['active-v1','good-v2','mixed-kem']};D['status']='passed'
except Exception as e:
    D['status']='failed';D['error']=repr(e)
    D.setdefault('endpoint_diagnostics',{})
    for role in started:
        try:D['endpoint_diagnostics'][role]=worker(role,{'action':'diagnostics'})
        except Exception:pass
    raise
finally:
    for role in started:
        try:worker(role,{'action':'cleanup'})
        except Exception as e:D.setdefault('cleanup_errors',[]).append(str(e))
        try:cmd(role,f'sudo docker rm -f kpqc-systems-{role}')
        except Exception as e:D.setdefault('cleanup_errors',[]).append(str(e))
    for role in networks:
        try:cmd(role,f'sudo docker network rm kpqc-systems-{role}')
        except Exception as e:D.setdefault('cleanup_errors',[]).append(str(e))
    D['ended_at']=datetime.now(timezone.utc).isoformat();save(final=True);print('RESULTS:',OUT,flush=True)
