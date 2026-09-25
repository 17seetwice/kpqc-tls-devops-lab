#!/usr/bin/env python3
#배포·장애 주입·복구의 전체 순서
"""One release lifecycle: classical service, SLO admission, PQC recovery."""
import argparse,json,os,shlex,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
p=argparse.ArgumentParser();p.add_argument('--local',action='store_true');p.add_argument('--smoke',action='store_true');p.add_argument('--server');p.add_argument('--client');p.add_argument('--server-private');p.add_argument('--image',default='kpqc-lab:gate');a=p.parse_args()
ROOT=Path(__file__).resolve().parents[1];RUN=datetime.now(timezone.utc).strftime(('local' if a.local else 'aws')+'-release-%Y%m%dT%H%M%SZ');OUT=ROOT/'artifacts'/RUN;OUT.mkdir(parents=True)
HOSTS={'server':a.server,'client':a.client};started=[];networks=[]
D={'run_id':RUN,'status':'running','smoke':a.smoke,'source_commit':os.getenv('GITHUB_SHA'),'image_identity':os.getenv('KPQC_IMAGE_ID','local-unattested'),'started_at':datetime.now(timezone.utc).isoformat(),'assertions':[],'candidates':[]}
def save():
    temp=OUT/'results.tmp';temp.write_text(json.dumps(D));os.replace(temp,OUT/'results.json')
def check(name,ok):
    D['assertions'].append({'name':name,'passed':bool(ok)});save();print(name,'PASS' if ok else 'FAIL',flush=True);assert ok,name

def cmd(role,command,data=None,timeout=180):
    if a.local:argv=['sh','-c',command.replace('sudo docker','docker')]
    else:argv=['ssh','-i',str(ROOT/'kpqc-devops-lab.pem'),'-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlias=kpqc-'+role,'-o',f'UserKnownHostsFile={ROOT}/.aws-runtime/known_hosts','-o','ControlMaster=auto','-o','ControlPersist=600','-o',f'ControlPath={ROOT}/.aws-runtime/rel-%h','ubuntu@'+HOSTS[role],command]
    r=subprocess.run(argv,input=data,capture_output=True,timeout=timeout)
    if r.returncode:raise RuntimeError(role+': '+r.stderr.decode(errors='replace')[-1500:])
    return r.stdout

def worker(role,q):return json.loads(cmd(role,f'sudo docker exec -i kpqc-release-{role} python3 /app/scripts/release_worker.py',json.dumps(q).encode()))
def health(route='active'):return worker('client',{'action':'health','ip':IP,'route':route})
def expected(row,fingerprint,group=65056,sig=65408):
    t=row.get('tls',{});return row.get('ok') and t.get('verify_result')==0 and not t.get('reused') and t.get('peer_certificate_sha256')==fingerprint and t.get('group_code')==group and t.get('signature_code')==sig
try:
    for role in HOSTS:
        name='kpqc-release-'+role
        cmd(role,f'sudo docker network create --opt com.docker.network.driver.mtu=1500 {name}');networks.append(role)
        port=' -p 4433:4433' if role=='server' else ''
        cmd(role,f'sudo docker run -d --init --name {name} --network {name}{port} --cpus 2 --memory 512m --tmpfs /state:size=64m --tmpfs /results:size=128m -e KPQC_RELEASE_SMOKE={int(a.smoke)} -e KPQC_IMAGE_ID={shlex.quote(os.getenv("KPQC_IMAGE_ID","local-unattested"))} {shlex.quote(a.image)}');started.append(role)
    IP=json.loads(cmd('client','sudo docker network inspect kpqc-release-client'))[0]['IPAM']['Config'][0]['Gateway'] if a.local else a.server_private
    init=worker('server',{'action':'init-server'});worker('client',{'action':'init-client','trust':init['trust']})
    policy=init['release_policy'];finger=init['certificate_sha256'];D.update(policy=policy,policy_sha256=init['release_policy_sha256'],certificate_sha256=finger)
    D['legacy_baseline']=worker('client',{'action':'window','ip':IP,'route':'active','seconds':2})
    check('actual-classical-service',all(expected(r,finger['active-v1'],29,1027) for r in D['legacy_baseline']['rows']))
    # Longer than the 15-second accept timeout which formerly killed idle workers.
    time.sleep(17);D['idle_health']=health();D['idle_workers']=worker('server',{'action':'workers'})
    check('idle-listener-stays-available',expected(D['idle_health'],finger['active-v1'],29,1027) and D['idle_workers']['active_workers']==8)
    for name in ['slow-v2','good-v2','good-v3']:
        before=worker('server',{'action':'state'})
        binding=worker('server',{'action':'candidate','name':name})['route']['candidate']
        probes={c:worker('client',{'action':'probe','ip':IP,'route':'candidate','client':c,'trust':'all'}) for c in ['broad','pqc','classical_kem','classical_signature','legacy','tls12']}
        evidence={'binding':binding,'ready':True,'probes':probes}
        perf={'binding':binding,'windows':[]}
        for block in range(policy['required_windows']):
            result=worker('client',{'action':'window','ip':IP,'route':'candidate'});result['block']=block;perf['windows'].append(result)
        q={'candidate':name,'evidence':evidence,'performance':perf}
        verdict=worker('server',{'action':'decision',**q})
        record={'candidate':name,'binding':binding,'probes':probes,'performance':perf,'decision':verdict};D['candidates'].append(record);save()
        check(name+'-cryptographic-policy',verdict['crypto']['deployment_allowed'])
        if name=='slow-v2':
            check('slow-candidate-fails-only-performance',not verdict['deployment_allowed'] and 'P95_LATENCY_BUDGET_EXCEEDED' in verdict['performance']['reasons'])
            try:worker('server',{'action':'promote',**q});blocked=False
            except RuntimeError:blocked=True
            check('promotion-cannot-bypass-performance',blocked)
            worker('server',{'action':'discard'});record['active_after_rejection']=health()
            check('rejection-keeps-classical-active',expected(record['active_after_rejection'],finger['active-v1'],29,1027))
        else:
            check(name+'-performance-admission',verdict['deployment_allowed'])
            record['promotion']=worker('server',{'action':'promote',**q});record['active_after_promotion']=health()
            check(name+'-observed-new-certificate',expected(record['active_after_promotion'],finger[name]))
            if name=='good-v2':
                D['classical_rollback_rejection']=worker('server',{'action':'rollback'})
                check('cannot-rollback-to-classical',D['classical_rollback_rejection']['restored'] is False and D['classical_rollback_rejection']['reason']=='NO_APPROVED_PQC_ROLLBACK_TARGET')
    D['before_fault']=health();check('v3-healthy-before-injection',expected(D['before_fault'],finger['good-v3']))
    D['wrong_rollback_health']=worker('server',{'action':'rollback','health':D['before_fault'],'health_observed_at_ns':time.time_ns()})
    check('rollback-rejects-wrong-certificate',D['wrong_rollback_health'].get('reason')=='ROLLBACK_TARGET_NOT_HEALTHY')
    old_health=health('rollback')
    D['stale_rollback_health']=worker('server',{'action':'rollback','health':old_health,'health_observed_at_ns':time.time_ns()-10_000_000_000})
    check('rollback-rejects-stale-health',D['stale_rollback_health'].get('reason')=='STALE_ROLLBACK_HEALTH')
    worker('client',{'action':'window-launch','ip':IP,'route':'active','seconds':15})
    time.sleep(2)
    t0=time.monotonic_ns();D['fault']=worker('server',{'action':'fault-active'});D['health_checks']=[];failures=0
    for _ in range(12):
        r=health();D['health_checks'].append({'elapsed_ms':(time.monotonic_ns()-t0)/1e6,'row':r})
        failures=0 if expected(r,finger['good-v3']) else failures+1
        if failures>=policy['consecutive_failures_to_rollback']:break
        time.sleep(policy['health_interval_seconds'])
    check('automatic-failure-detection',failures>=policy['consecutive_failures_to_rollback'])
    D['detection_ms']=(time.monotonic_ns()-t0)/1e6
    target=health('rollback');D['rollback_health']=target;check('previous-approved-version-still-live',expected(target,finger['good-v2']))
    D['rollback']=worker('server',{'action':'rollback','health':target,'health_observed_at_ns':time.time_ns()})
    check('automatic-pqc-rollback',D['rollback']['restored'])
    D['recovered_health']=health();D['recovery_ms']=(time.monotonic_ns()-t0)/1e6
    check('recovery-objective',expected(D['recovered_health'],finger['good-v2']) and D['recovery_ms']<=policy['recovery_objective_seconds']*1000)
    D['recovery_traffic']=worker('client',{'action':'window-collect'});rows=D['recovery_traffic']['rows'];good=[r for r in rows if r['ok']]
    check('fault-window-observed-both-pqc-versions',{r['tls']['peer_certificate_sha256'] for r in good}=={finger['good-v2'],finger['good-v3']})
    check('recovery-traffic-never-classical',all(expected(r,finger['good-v2']) or expected(r,finger['good-v3']) for r in good))
    last_failure=max((r['sequence'] for r in rows if not r['ok']),default=-1)
    check('sustained-restored-traffic',len(rows)-last_failure-1>=20 and all(expected(r,finger['good-v2']) for r in rows[-20:]))
    D['post_recovery_probes']={c:worker('client',{'action':'probe','ip':IP,'route':'active','client':c,'trust':'all'}) for c in ['broad','pqc','classical_kem','classical_signature','legacy','tls12']}
    import gate_policy
    crypto=json.loads((ROOT/'policies/pqc-required.json').read_text())
    D['post_recovery_decision']=gate_policy.evaluate({'ready':True,'probes':D['post_recovery_probes']},crypto)
    check('restored-service-maintains-crypto-policy',D['post_recovery_decision']['deployment_allowed'])
    D['status']='passed'
except Exception as e:D['status']='failed';D['error']=repr(e);raise
finally:
    for role in started:
        try:worker(role,{'action':'cleanup'})
        except Exception as e:D.setdefault('cleanup_errors',[]).append(str(e))
        try:cmd(role,f'sudo docker rm -f kpqc-release-{role}')
        except Exception as e:D.setdefault('cleanup_errors',[]).append(str(e))
    for role in networks:
        try:cmd(role,f'sudo docker network rm kpqc-release-{role}')
        except Exception as e:D.setdefault('cleanup_errors',[]).append(str(e))
    D['ended_at']=datetime.now(timezone.utc).isoformat();save();print('RESULTS',OUT,flush=True)
