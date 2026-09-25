"""Validate and summarize one balanced AWS latency run; never pool prior runs."""
import json, csv, statistics as st, sys
from pathlib import Path
source=Path(sys.argv[1]); out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
d=json.loads(source.read_text());assert d['status']=='passed' and d['cleanup_ok']
schedule=d['schedule'];assert len(schedule)==20
assert sum(p['mode']=='cold' for p in schedule[::2])==5
rows={};blockrows=[];count=0
codes={'X25519':29,'smaug1':65056,'smaug3':65059,'smaug5':65062,'ntruplus_kem576':65064,'ntruplus_kem768':65067,'ntruplus_kem864':65070,'ntruplus_kem1152':65073}
sigs={'EC':1027,'haetae2':65408,'haetae3':65409,'haetae5':65410,'aimer128f':65411,'aimer192f':65413,'aimer256f':65415}
expected={('X25519','EC')}|{(k,s) for k in codes if k!='X25519' for s in sigs if s!='EC'}
assert len(d['rounds'])==20
for a,b in zip(schedule[::2],schedule[1::2]):
 assert a['block']==b['block'] and a['configuration_order']==b['configuration_order'] and {a['mode'],b['mode']}=={'cold','warm'}
for plan,block in zip(schedule,d['rounds']):
 assert (plan['mode'],plan['block'])==(block['mode'],block['block'])
 profiles=block['profiles']; assert len(profiles)==45 and profiles[0]['sentinel'] and profiles[-1]['sentinel']
 assert [(p['kem'],p['signature']) for p in profiles[1:-1]]==[tuple(p) for p in plan['configuration_order']]
 assert {(p['kem'],p['signature']) for p in profiles[1:-1]}==expected
 for p in profiles:
  mode=block['mode'];ss=p['sessions'];assert len(ss)==(5 if mode=='warm' else 3)
  for i,s in enumerate(ss):
   count+=1; assert s['repeat']==i and s['warmup']==(mode=='warm' and i<2)
   c,t=s['client'],s['server']
   for r in [c,t]:
    assert r['success'] and r['verify_result']==0 and not r['reused'] and r['hello_retry_requests']==0
    assert r['tls_version']=='TLSv1.3' and r['cipher']=='TLS_AES_256_GCM_SHA384'
    assert r['group_code']==codes[p['kem']] and r['signature_code']==sigs[p['signature']]
    assert r['handshake_ms']>0 and r['cpu_ms']>=0
   assert c['sent_handshake_bytes']==t['received_handshake_bytes'] and t['sent_handshake_bytes']==c['received_handshake_bytes']
  if not p['sentinel']:
   keep=[s['client']['handshake_ms'] for s in ss if not s['warmup']]
   rows.setdefault((mode,p['kem'],p['signature']),[]).extend(keep)
   blockrows.append({'block':block['block'],'mode':mode,'kem':p['kem'],'signature':p['signature'],'median_ms':st.median(keep),'first_mode':schedule[block['block']*2]['mode']})
assert count==3600 and len(rows)==86 and all(len(v)==30 for v in rows.values())
summ=[]
for (mode,k,s),v in rows.items():summ.append({'mode':mode,'kem':k,'signature':s,'n':len(v),'median_ms':st.median(v)})
for name,values in [('summary',summ),('blocks',blockrows)]:
 with (out/f'{name}.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=values[0],lineterminator='\n');w.writeheader();w.writerows(values)
summary={'run_id':d['run_id'],'source_commit':d['source_commit'],'image_identity':d['image_identity'],'collected':count,'analyzed':sum(map(len,rows.values())),'modes':{}}
for mode in ('cold','warm'):
 pq=[st.median(v) for (m,k,s),v in rows.items() if m==mode and k!='X25519']
 summary['modes'][mode]={'baseline_ms':st.median(rows[mode,'X25519','EC']),'pqc_configuration_median_range_ms':[min(pq),max(pq)]}
(out/'audit.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
paired=[]
lookup={(r['block'],r['mode'],r['kem'],r['signature']):r for r in blockrows}
for k,s in sorted(expected):
 ratios=[];by_first={'cold':[],'warm':[]}
 for b in range(10):
  c=lookup[b,'cold',k,s];w=lookup[b,'warm',k,s]
  ratio=w['median_ms']/c['median_ms'];ratios.append(ratio);by_first[c['first_mode']].append(ratio)
 paired.append({'kem':k,'signature':s,'paired_blocks':10,'median_warm_cold_ratio':st.median(ratios),'cold_first_median_ratio':st.median(by_first['cold']),'warm_first_median_ratio':st.median(by_first['warm'])})
with (out/'paired.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=paired[0],lineterminator='\n');w.writeheader();w.writerows(paired)
# Publication figures use identical axes and the full configuration matrix.
import os
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[2]/'.mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
def label(s):return s.replace('ntruplus_kem','NTRU+ ').replace('smaug','SMAUG ').replace('haetae','HAETAE ').replace('aimer','AIMer ').replace('EC','ECDSA')
for lang in ('ko','en'):
 folder=out/lang;folder.mkdir(exist_ok=True)
 plt.rcParams.update({'font.family':'Apple SD Gothic Neo' if lang=='ko' else 'DejaVu Sans','font.size':11,'svg.fonttype':'path','axes.unicode_minus':False})
 for family,ks in [('smaug',['X25519','smaug1','smaug3','smaug5']),('ntru',['ntruplus_kem576','ntruplus_kem768','ntruplus_kem864','ntruplus_kem1152'])]:
  fig,axs=plt.subplots(2,2,figsize=(12.8,7.8),layout='constrained')
  limit=max(st.median(v) for v in rows.values())*1.15
  for panel,(ax,k) in enumerate(zip(axs.flat,ks)):
   siglist=['EC'] if k=='X25519' else [s for s in sigs if s!='EC']
   for y,s in enumerate(siglist):
    for mode,dy,color,marker in [('cold',-.13,'#0072B2','o'),('warm',.13,'#D55E00','s')]:
     v=st.median(rows[mode,k,s]);ax.plot(v,y+dy,marker=marker,color=color,ms=7,ls='');ax.annotate(f'{v:.2f}',(v,y+dy),xytext=(7,0),textcoords='offset points',va='center',fontsize=9,color=color)
   ax.set_yticks(range(len(siglist)),[label(s) for s in siglist]);ax.set_ylim(len(siglist)-.5,-.5);ax.set_xlim(0,limit)
   ax.set_title(f'({chr(97+panel)}) {label(k)}',loc='left',fontsize=13,pad=12)
   ax.set_xlabel('핸드셰이크 시간 (ms)' if lang=='ko' else 'Handshake latency (ms)')
   ax.spines[['top','right','left']].set_visible(False);ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
  labs=['새 프로세스','프로세스 재사용'] if lang=='ko' else ['Fresh process','Reused process']
  fig.legend(handles=[Line2D([],[],ls='',marker=m,color=c,label=l) for l,m,c in zip(labs,['o','s'],['#0072B2','#D55E00'])],loc='outside upper center',ncol=2,frameon=False)
  for ext in ('png','svg'):fig.savefig(folder/f'latency_{family}.{ext}',dpi=200,bbox_inches='tight')
  plt.close(fig)
