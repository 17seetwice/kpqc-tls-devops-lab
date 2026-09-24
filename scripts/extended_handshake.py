#!/usr/bin/env python3
"""Randomized full-handshake blocks; warm/cold latency and separate RSS experiment."""
import argparse,json,os,random,shlex,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
ap=argparse.ArgumentParser();ap.add_argument('--server');ap.add_argument('--client');ap.add_argument('--server-private');ap.add_argument('--image',default='0923_kpqc_devops-gate');ap.add_argument('--local',action='store_true');ap.add_argument('--smoke',action='store_true');args=ap.parse_args()
ROOT=Path(__file__).resolve().parents[1]
RUN=datetime.now(timezone.utc).strftime(('local' if args.local else 'aws')+'-extended-%Y%m%dT%H%M%SZ')
OUT=(Path('/results-root') if args.local else ROOT/'artifacts')/RUN;OUT.mkdir(parents=True)
if args.local:
    Path('/results').symlink_to(OUT,target_is_directory=True)
    import handshake_worker
IP='127.0.0.1' if args.local else args.server_private
hosts={'server':args.server,'client':args.client}
def cmd(role,command,data=None):
    return subprocess.run(['ssh','-i',str(ROOT/'kpqc-devops-lab.pem'),'-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlias=kpqc-'+role,'-o',f'UserKnownHostsFile={ROOT}/.aws-runtime/known_hosts','-o','ControlMaster=auto','-o','ControlPersist=600','-o',f'ControlPath={ROOT}/.aws-runtime/ext-%h','ubuntu@'+hosts[role],command],input=data,check=True,capture_output=True,timeout=300).stdout

def worker(role,q):
    if args.local:return handshake_worker.main(q)
    return json.loads(cmd(role,'sudo docker exec -i kpqc-extended python3 /app/scripts/handshake_worker.py',json.dumps(q).encode()))
D={'run_id':RUN,'status':'running','started_at':datetime.now(timezone.utc).isoformat(),'image_identity':os.environ.get('KPQC_IMAGE_ID','local-unattested'),'rounds':[],'measurement':{'latency':'client SSL_connect only; server SSL_accept recorded separately','warm':'one context/process per block, first 2 full handshakes retained but excluded from summary; no resumption','cold':'new process/context each connection; no warmup exclusion','blocks':'5 rounds per latency mode; each round shuffles 43 configurations with fixed seed; one AWS execution, not independent instance replications','memory':'separate cold run, reset Linux VmHWM immediately before SSL call; peak increase over reset baseline; not allocation bytes','bytes':'message callback TLS handshake message bytes, directional; excludes record headers/TCP/IP','network':'host networking on EC2; same-AZ private IPv4'}}
started=[]
def save(): (OUT/'results.json').write_text(json.dumps(D,indent=2))
try:
    if not args.local:
        for role in hosts:
            cmd(role,f'mkdir -p kpqc-devops-lab/results/{RUN} && sudo docker run -d --init --name kpqc-extended --network host --cpus 2 --memory 512m --tmpfs /state:size=64m -v "$HOME/kpqc-devops-lab/results/{RUN}:/results" {shlex.quote(args.image)}');started.append(role)
    trust=worker('server',{'action':'init-server'});worker('client',{'action':'init-client','trust':trust['trust']})
    D['metadata_before']={r:worker(r,{'action':'metadata'}) for r in hosts}
    D['memory_selftests']={r:worker(r,{'action':'memory-selftest'}) for r in hosts}
    codes={'X25519':29,'smaug1':65056,'smaug3':65059,'smaug5':65062,'ntruplus_kem576':65064,'ntruplus_kem768':65067,'ntruplus_kem864':65070,'ntruplus_kem1152':65073}
    sigs={'EC':1027,'haetae2':65408,'haetae3':65409,'haetae5':65410,'aimer128f':65411,'aimer192f':65413,'aimer256f':65415}
    pairs=[('X25519','EC')]+[(k,s) for k in codes if k!='X25519' for s in sigs if s!='EC']
    if args.smoke:pairs=[('X25519','EC'),('smaug1','haetae2'),('ntruplus_kem768','aimer128f')]
    rng=random.Random(20260925)
    for mode in ['cold','warm','memory']:
        for block in range(1 if args.smoke or mode=='memory' else 5):
            order=list(pairs);rng.shuffle(order)
            # Sentinels bracket each block; marked separately to avoid baseline weighting bias.
            order=[('X25519','EC')]+order+[('X25519','EC')]
            rd={'mode':mode,'block':block,'profiles':[]};D['rounds'].append(rd)
            for index,(k,s) in enumerate(order):
                tag=f'{mode}-{block}-{index}-{k}-{s}';count=5 if mode=='warm' else 3
                q={'kem':k,'signature':s,'tag':tag,'count':count,'warm':mode=='warm','memory':mode=='memory'}
                worker('server',{'action':'start',**q,'tag':tag+'-server'})
                cs=worker('client',{'action':'clients',**q,'ip':IP})['rows'];ss=worker('server',{'action':'collect','tag':tag+'-server'})['rows']
                assert len(cs)==len(ss)==count
                rows=[]
                for i,(c,t) in enumerate(zip(cs,ss)):
                    for r in [c,t]:
                        assert r['success'] and r['group_code']==codes[k] and r['signature_code']==sigs[s] and not r['reused'] and r['verify_result']==0
                        if mode=='memory':assert r['rss_peak_reset_ok'] and r['rss_window_peak_growth_kib']>=0
                    rows.append({'repeat':i,'warmup':mode=='warm' and i<2,'client':c,'server':t})
                rd['profiles'].append({'kem':k,'signature':s,'sentinel':index in (0,len(order)-1),'sessions':rows})
                save();print(mode,block,index,k,s,'PASS',flush=True)
    D['metadata_after']={r:worker(r,{'action':'metadata'}) for r in hosts};D['status']='passed'
except Exception as e:D['error']=repr(e);D['status']='failed';raise
finally:
    for role in (['server'] if args.local else started):
        try:
            worker(role,{'action':'cleanup'})
            if not args.local:cmd(role,'sudo docker rm -f kpqc-extended')
        except Exception as e:D.setdefault('cleanup_errors',[]).append(str(e))
    D['ended_at']=datetime.now(timezone.utc).isoformat();save();print('RESULTS:',OUT,flush=True)
