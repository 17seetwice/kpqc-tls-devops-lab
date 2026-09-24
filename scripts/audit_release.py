#!/usr/bin/env python3
"""Independently check public release records; never infer success from workflow alone."""
import argparse,hashlib,json,statistics
from pathlib import Path
import gate_policy,release_policy
p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--out',required=True);a=p.parse_args()
source=Path(a.source);d=json.loads(source.read_text());out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
assert d['status']=='passed' and not d['smoke'] and d.get('cleanup_ok',not d.get('cleanup_errors'))
assert all(x['passed'] for x in d['assertions'])
root=Path(__file__).resolve().parents[1]
policy=json.loads((root/'policies/release-slo.json').read_text());crypto=json.loads((root/'policies/pqc-required.json').read_text())
assert policy==d['policy'] and hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()==d['policy_sha256']
finger=d['certificate_sha256']
def valid(r,name,group=65056,sig=65408):
 t=r['tls'];assert r['ok'] and r['returncode']==0 and t['success'] and t['verify_result']==0 and not t['reused']
 assert t['peer_certificate_sha256']==finger[name] and t['group_code']==group and t['signature_code']==sig
 assert t['tls_version']=='TLSv1.3' and t['cipher']=='TLS_AES_256_GCM_SHA384'
for row in d['legacy_baseline']['rows']:valid(row,'active-v1',29,1027)
valid(d['idle_health'],'active-v1',29,1027);assert d['idle_workers']['active_workers']==8
assert [c['candidate'] for c in d['candidates']]==['slow-v2','good-v2','good-v3']
summary=[]
for c in d['candidates']:
 ev=c['performance'];binding=c['binding'];assert binding['release_policy_sha256']==d['policy_sha256']
 assert gate_policy.evaluate({'ready':True,'probes':c['probes']},crypto)['deployment_allowed']
 expected=c['candidate']!='slow-v2'
 assert c['decision']['deployment_allowed']==expected
 # Freshness was checked at decision time; re-evaluate relative to final window.
 now=max(w['observed_at_ns'] for w in ev['windows'])+1
 result=release_policy.evaluate(ev,policy,binding,now);assert result['passed']==expected
 assert result['windows']==c['decision']['performance']['windows']
 for w in ev['windows']:
  assert w['start_ns']<w['end_ns']
  for r in w['rows']:
   assert r['scheduled_ns']>=w['start_ns'] and r['ended_ns']<=w['end_ns']
   assert abs(r['admission_ms']-(r['ended_ns']-r['scheduled_ns'])/1e6)<1e-6
   assert abs(r['generator_lateness_ms']-max(0,(r['started_ns']-r['scheduled_ns'])/1e6))<1e-6
   if r['ok']:valid(r,c['candidate'])
  for i,r in enumerate(w['rows']):assert abs(r['scheduled_ns']-w['start_ns']-round(i*1e9/w['rate']))<=1
 vals=result['windows']
 summary.append({'candidate':c['candidate'],'cryptographic_pass':True,'admitted':expected,'attempts':sum(x['scheduled'] for x in vals),
  'successes':sum(x['successes'] for x in vals),'p95_admission_ms_by_window':[x['p95_admission_ms'] for x in vals],
  'p95_tls_ms_by_window':[x['tls_p95_ms'] for x in vals],'on_time_fraction_by_window':[x['on_time_fraction'] for x in vals]})
 if expected:valid(c['active_after_promotion'],c['candidate'])
 else:valid(c['active_after_rejection'],'active-v1',29,1027)
assert d['classical_rollback_rejection']['restored'] is False
assert d['wrong_rollback_health']['reason']=='ROLLBACK_TARGET_NOT_HEALTHY'
assert d['stale_rollback_health']['reason']=='STALE_ROLLBACK_HEALTH'
assert len(d['health_checks'])>=2 and all(not x['row']['ok'] for x in d['health_checks'][-2:])
assert d['rollback']['restored'] and d['rollback']['after']['version']=='good-v2'
valid(d['rollback_health'],'good-v2');valid(d['recovered_health'],'good-v2')
assert 0<=d['detection_ms']<=d['recovery_ms']<=policy['recovery_objective_seconds']*1000
traffic=d['recovery_traffic'];rows=traffic['rows'];assert len(rows)==150 and [r['sequence'] for r in rows]==list(range(150))
for r in rows:
 if r['ok']:valid(r,'good-v2' if r['tls']['peer_certificate_sha256']==finger['good-v2'] else 'good-v3')
for r in rows[-20:]:valid(r,'good-v2')
assert gate_policy.evaluate({'ready':True,'probes':d['post_recovery_probes']},crypto)['deployment_allowed']
result={'status':'passed','run_id':d['run_id'],'source_commit':d['source_commit'],'image_identity':d['image_identity'],
 'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'policy_sha256':d['policy_sha256'],'assertions':len(d['assertions']),
 'candidate_summary':summary,'detection_ms':d['detection_ms'],'recovery_ms':d['recovery_ms'],
 'recovery_scheduled':len(rows),'recovery_failures':sum(not r['ok'] for r in rows),
 'old_pqc_successes':sum(r['ok'] and r['tls']['peer_certificate_sha256']==finger['good-v3'] for r in rows),
 'restored_pqc_successes':sum(r['ok'] and r['tls']['peer_certificate_sha256']==finger['good-v2'] for r in rows)}
(out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
