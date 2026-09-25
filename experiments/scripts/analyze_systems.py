#!/usr/bin/env python3
"""Audit the public systems artifact and produce paired, block-level research figures."""
import argparse,csv,gzip,hashlib,json,statistics as st
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ap=argparse.ArgumentParser();ap.add_argument('source');ap.add_argument('--out',default='experiments/network-and-load');ap.add_argument('--rollout-source');ap.add_argument('--performance-only',action='store_true');a=ap.parse_args()
source=Path(a.source);raw=gzip.decompress(source.read_bytes()) if source.suffix=='.gz' else source.read_bytes();D=json.loads(raw);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
assert D.get('cleanup_ok',True)
failed=[x['name'] for x in D['assertions'] if not x['passed']]
if D['status']!='passed':
    assert D['status']=='failed' and failed==['rollout-both-approved-identities']
    assert a.performance_only or a.rollout_source
RD=None;roll_raw=None
if a.rollout_source:
    rp=Path(a.rollout_source);roll_raw=gzip.decompress(rp.read_bytes()) if rp.suffix=='.gz' else rp.read_bytes();RD=json.loads(roll_raw)
    assert RD['status']=='passed' and RD.get('cleanup_ok',True) and all(x['passed'] for x in RD['assertions'])
elif not a.performance_only:RD=D

K={'X25519':29,'smaug1':65056,'ntruplus_kem768':65067};S={'EC':1027,'haetae2':65408,'aimer128f':65411}
PROFILES=[('X25519','EC')]+[(k,s) for k in ['smaug1','ntruplus_kem768'] for s in ['haetae2','aimer128f']]
NAMES={('X25519','EC'):'X25519 + ECDSA P-256',('smaug1','haetae2'):'SMAUG1 + HAETAE2',('smaug1','aimer128f'):'SMAUG1 + AIMer128f',('ntruplus_kem768','haetae2'):'NTRU+ KEM768 + HAETAE2',('ntruplus_kem768','aimer128f'):'NTRU+ KEM768 + AIMer128f'}
def valid(r,k,s,hrr=0):
    assert r['success'] and r['verify_result']==0 and not r['reused']
    assert r['group_code']==K[k] and r['signature_code']==S[s] and r['hello_retry_requests']==hrr
    assert r['tls_version']=='TLSv1.3' and r['cipher']=='TLS_AES_256_GCM_SHA384'
    assert r['handshake_ms']>0 and r['cpu_ms']>=0

def csvfile(name,rows):
    with (out/name).open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
net=[];hrr=[]
for key,table in [('network',net),('hrr',hrr)]:
    seen=set()
    for item in D[key]:
        k,s=item['kem'],item['signature'];expected=int(item.get('induced_hrr',False))
        ident=(item['block'],k,s,item['mtu'],item['egress_delay_ms'],expected)
        assert ident not in seen;seen.add(ident)
        assert len(item['sessions'])==5 and [r['warmup'] for r in item['sessions']]==[True,True,False,False,False]
        for row in item['sessions']:
            c,t=row['client'],row['server'];valid(c,k,s,expected);valid(t,k,s,expected)
            assert c['sent_handshake_bytes']==t['received_handshake_bytes'] and t['sent_handshake_bytes']==c['received_handshake_bytes']
            if key=='network':
                assert c['tcp_snd_mss']<=item['mtu']-40 and t['tcp_snd_mss']<=item['mtu']-40
                if item['mtu']==9001:assert min(c['tcp_snd_mss'],t['tcp_snd_mss'])>1460
        rows=[r['client'] for r in item['sessions'] if not r['warmup']]
        table.append({'block':item['block'],'kem':k,'signature':s,'mtu':item['mtu'],'added_rtt_ms':2*item['egress_delay_ms'],'hrr':expected,'n':len(rows),'median_ms':st.median(r['handshake_ms'] for r in rows),'tcp_rtt_median_ms':st.median(r['tcp_rtt_us']/1000 for r in rows),'sent_handshake_bytes':st.median(r['sent_handshake_bytes'] for r in rows),'received_handshake_bytes':st.median(r['received_handshake_bytes'] for r in rows),'snd_mss_min':min(r['tcp_snd_mss'] for r in rows),'snd_mss_max':max(r['tcp_snd_mss'] for r in rows)})
load=[];total=0
for item in D['throughput']:
    k,s=item['kem'],item['signature'];data=item['load'];rows=data['rows'];n=item['concurrency'];total+=len(rows)
    assert len(data['returncodes'])==n and all(x==0 for x in data['returncodes'])
    assert {r['worker'] for r in rows}==set(range(n))
    assert item['server_cpu_before']['server_worker_count']==item['server_cpu_after']['server_worker_count']==8
    assert len(item['priming_sessions'])==16
    for r in item['priming_sessions']:valid(r,k,s)
    for r in rows:
        valid(r,k,s);assert r['tcp_ready_and_handshake_ms']>=r['handshake_ms']
        assert data['start_ns']<=r['completed_monotonic_ns']<=data['end_ns']
    load.append({'block':item['block'],'kem':k,'signature':s,'concurrency':n,'connections':len(rows),'failed':sum(not r['success'] for r in rows),'elapsed_seconds':data['elapsed_seconds'],'handshakes_per_second':len(rows)/data['elapsed_seconds'],'tls_p50_ms':st.median(r['handshake_ms'] for r in rows),'tls_p95_ms':float(np.quantile([r['handshake_ms'] for r in rows],.95)),'tcp_ready_tls_p50_ms':st.median(r['tcp_ready_and_handshake_ms'] for r in rows),'tcp_ready_tls_p95_ms':float(np.quantile([r['tcp_ready_and_handshake_ms'] for r in rows],.95))})
assert len(net)==90 and len(hrr)==72 and len(load)==45,'Expected full AWS design, not smoke data'
for table,fields in [(net,['kem','signature','mtu','added_rtt_ms']),(hrr,['kem','signature','added_rtt_ms','hrr']),(load,['kem','signature','concurrency'])]:
    groups=defaultdict(list)
    for r in table:groups[tuple(r[k] for k in fields)].append(r)
    assert all({r['block'] for r in rows}=={0,1,2} and len(rows)==3 for rows in groups.values())
if RD is not None:
    roll=RD['rollout_load'];finger=RD['rollout_certificate_sha256'];counts=Counter(r['peer_certificate_sha256'] for r in roll['rows'])
    assert set(counts)=={finger['active-v1'],finger['good-v2']} and all(x==0 for x in roll['returncodes'])
    assert len(roll['returncodes'])==4 and {r['worker'] for r in roll['rows']}=={0,1,2,3}
    assert RD['post_promotion_hold_seconds']==60
    first_new=min(r['completed_monotonic_ns'] for r in roll['rows'] if r['peer_certificate_sha256']==finger['good-v2'])
    last_new=max(r['completed_monotonic_ns'] for r in roll['rows'] if r['peer_certificate_sha256']==finger['good-v2'])
    assert (last_new-first_new)/1e9>=60, 'Require observed post-promotion traffic for at least 60 seconds'
    for r in roll['rows']:valid(r,'smaug1','haetae2')
    assert [(x['candidate'],x['decision']['deployment_allowed']) for x in RD['rollout']]==[('mixed-kem',False),('good-v2',True)]
    for x in RD['rollout']:assert not x['progress']['done']
csvfile('network_blocks.csv',net);csvfile('hrr_blocks.csv',hrr);csvfile('throughput_blocks.csv',load)
# Paired contrasts within each block, never confidence intervals from three blocks.
contrasts=[]
for k,s in PROFILES:
    for rtt in [0,10,30]:
        for block in range(3):
            rows={r['mtu']:r for r in net if (r['kem'],r['signature'],r['added_rtt_ms'],r['block'])==(k,s,rtt,block)}
            contrasts.append({'kind':'mtu1500-minus9001','kem':k,'signature':s,'added_rtt_ms':rtt,'block':block,'delta_ms':rows[1500]['median_ms']-rows[9001]['median_ms']})
            if k!='X25519':
                rows={r['hrr']:r for r in hrr if (r['kem'],r['signature'],r['added_rtt_ms'],r['block'])==(k,s,rtt,block)}
                contrasts.append({'kind':'hrr-minus-control','kem':k,'signature':s,'added_rtt_ms':rtt,'block':block,'delta_ms':rows[1]['median_ms']-rows[0]['median_ms']})
csvfile('paired_contrasts.csv',contrasts)
audit={'run_id':D['run_id'],'source_commit':D['source_commit'],'image_identity':D['image_identity'],
       'input_sha256':hashlib.sha256(raw).hexdigest(),'workflow_status':D['status'],
       'performance_assertions':sum(not x['name'].startswith(('rollout','under-load','rejection-')) for x in D['assertions']),
       'network_connections':len(net)*5,'network_analyzed':len(net)*3,'hrr_connections':len(hrr)*5,'hrr_analyzed':len(hrr)*3,
       'throughput_connections':total,'server_priming_connections':sum(len(i['priming_sessions']) for i in D['throughput']),
       'performance_audit':'passed',
       'initial_rollout':{'status':'failed' if failed else 'passed','recorded_connections':len(D.get('rollout_load',{}).get('rows',[])),
                         'client_exit_codes':D.get('rollout_load',{}).get('returncodes'),'failed_assertions':failed}}
if RD is not None:
    audit.update(rollout_run_id=RD['run_id'],rollout_source_commit=RD['source_commit'],rollout_image_identity=RD['image_identity'],
                 rollout_assertions=len(RD['assertions']),rollout_connections=len(roll['rows']),rollout_old_connections=counts[finger['active-v1']],
                 rollout_new_connections=counts[finger['good-v2']],rollout_failed=sum(not r['success'] for r in roll['rows']),
                 rollout_elapsed_seconds=roll['elapsed_seconds'],rollout_audit='passed')
    if roll_raw is not None:(out/'rollout.public.json.gz').write_bytes(gzip.compress(roll_raw,mtime=0))
(out/'audit.json').write_text(json.dumps(audit,indent=2))
(out/'measurements.public.json.gz').write_bytes(gzip.compress(raw,mtime=0))
COLORS=['#0072B2','#D55E00','#009E73','#CC79A7','#6C5B7B']
for lang in ['ko','en']:
    folder=out/lang;folder.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'Apple SD Gothic Neo' if lang=='ko' else 'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.unicode_minus':False,'svg.fonttype':'none'})
    def text(ko,en):return ko if lang=='ko' else en
    def finish(fig,name):
        fig.savefig(folder/(name+'.png'),dpi=190,bbox_inches='tight');fig.savefig(folder/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    fig,axes=plt.subplots(2,3,figsize=(13.5,7),sharex=True)
    for ax,(k,s) in zip(axes.flat,PROFILES):
        for mtu,color in [(1500,COLORS[1]),(9001,COLORS[0])]:
            ys=[]
            for x in [0,10,30]:
                vals=[r['median_ms'] for r in net if (r['kem'],r['signature'],r['mtu'],r['added_rtt_ms'])==(k,s,mtu,x)]
                ys.append(st.median(vals));ax.scatter([x]*3,vals,s=24,facecolors='none',edgecolors=color,alpha=.65)
            ax.plot([0,10,30],ys,'o-',color=color,label=f'MTU {mtu}')
        ax.set_title(NAMES[k,s],fontsize=11);ax.set_ylim(bottom=0);ax.set_xticks([0,10,30]);ax.tick_params(axis='x',labelbottom=True);ax.grid(axis='y',alpha=.18)
        ax.set_xlabel(text('설정한 추가 왕복 지연 (ms)','Configured added round-trip delay (ms)'));ax.set_ylabel(text('TLS 핸드셰이크 지연 (ms)','TLS handshake latency (ms)'))
    axes.flat[-1].axis('off');handles,labels=axes.flat[0].get_legend_handles_labels();axes.flat[-1].legend(handles,labels,loc='upper left',frameon=False)
    axes.flat[-1].text(.02,.53,text('빈 점: 블록별 중앙값\n선: 세 블록 중앙값의 중앙값\n\n각 조건: 3블록 × 분석 연결 3회\n동일한 컨테이너 브리지 구성','Open points: block medians\nLines: median of three block medians\n\nPer condition: 3 blocks × 3 analyzed connections\nIdentical container-bridge topology'),transform=axes.flat[-1].transAxes,va='top',linespacing=1.8)
    fig.suptitle(text('MTU와 네트워크 지연에 따른 TLS 핸드셰이크','TLS handshake sensitivity to MTU and network delay'),fontsize=16);fig.tight_layout(rect=[0,0,1,.94]);finish(fig,'01-network')
    fig,axes=plt.subplots(2,2,figsize=(11,7),sharex=True)
    for ax,(k,s) in zip(axes.flat,PROFILES[1:]):
        for retry,color,label in [(0,COLORS[0],text('기본 핸드셰이크','Matching-share control')),(1,COLORS[1],text('HRR 1회','One HRR'))]:
            ys=[]
            for x in [0,10,30]:
                vals=[r['median_ms'] for r in hrr if (r['kem'],r['signature'],r['hrr'],r['added_rtt_ms'])==(k,s,retry,x)];ys.append(st.median(vals));ax.scatter([x]*3,vals,s=22,facecolors='none',edgecolors=color,alpha=.6)
            ax.plot([0,10,30],ys,'o-',color=color,label=label)
        ax.set_title(NAMES[k,s],fontsize=11);ax.set_ylim(bottom=0);ax.set_xticks([0,10,30]);ax.tick_params(axis='x',labelbottom=True);ax.grid(axis='y',alpha=.18);ax.set_xlabel(text('설정한 추가 왕복 지연 (ms)','Configured added round-trip delay (ms)'));ax.set_ylabel(text('TLS 핸드셰이크 지연 (ms)','TLS handshake latency (ms)'))
    axes.flat[0].legend(frameon=False,fontsize=9)
    fig.suptitle(text('추가 키 공유 요청이 핸드셰이크에 미치는 영향','Handshake cost of HelloRetryRequest'),fontsize=16)
    fig.text(.5,.01,text('MTU 1500 · 빈 점: 블록별 중앙값 · 선: 세 블록 중앙값의 중앙값','MTU 1500 · Open points: block medians · Lines: median of three block medians'),ha='center',fontsize=10);fig.tight_layout(rect=[0,.03,1,.94]);finish(fig,'02-hrr')
    fig,axes=plt.subplots(1,3,figsize=(15,4.8))
    for ax,metric,title,ylabel in zip(axes,['handshakes_per_second','tls_p50_ms','tcp_ready_tls_p95_ms'],[text('서비스 처리량','Service throughput'),text('TLS 호출 지연 중앙값','Median SSL_connect latency'),text('대기 포함 접속 지연 p95','95th percentile including readiness wait')],[text('완료 연결 / 초','Completed handshakes / second'),'ms','ms']):
        for (k,s),color in zip(PROFILES,COLORS):
            ys=[]
            for n in [1,4,16]:
                vals=[r[metric] for r in load if (r['kem'],r['signature'],r['concurrency'])==(k,s,n)];ys.append(st.median(vals));ax.scatter([n]*3,vals,s=22,facecolors='none',edgecolors=color,alpha=.65)
            ax.plot([1,4,16],ys,'o-',color=color,label=NAMES[k,s])
        ax.set_title(title,fontsize=11);ax.set_xlabel(text('동시 클라이언트 수','Concurrent clients'));ax.set_ylabel(ylabel);ax.set_xticks([1,4,16]);ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.18)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=3,frameon=False,fontsize=9)
    fig.suptitle(text('병렬 TLS 서비스의 동시 접속 성능','Concurrent performance of the prefork TLS service'),fontsize=16)
    fig.text(.5,.91,text('조건별 8초 × 3회 · 빈 점: 반복별 값 · 선: 세 값의 중앙값','Three 8-second windows per condition · Open points: window statistics · Lines: median of three windows'),ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.16,1,.88]);finish(fig,'03-concurrency')
    if RD is not None:
        fig,ax=plt.subplots(figsize=(11,4.7))
        start=roll['start_ns'];old=[(r['completed_monotonic_ns']-start)/1e9 for r in roll['rows'] if r['peer_certificate_sha256']==finger['active-v1']];new=[(r['completed_monotonic_ns']-start)/1e9 for r in roll['rows'] if r['peer_certificate_sha256']==finger['good-v2']]
        bins=np.arange(0,np.ceil(roll['elapsed_seconds'])+1,1)
        ax.hist([old,new],bins=bins,stacked=True,color=[COLORS[0],COLORS[2]],label=[text('기존 활성 서비스','Previous active service'),text('승인된 새 서비스','Approved new service')],rwidth=.95)
        ax.set_xlabel(text('부하 시작 후 경과 시간 (s)','Elapsed time after load start (s)'));ax.set_ylabel(text('완료 연결 수 / 1초 구간','Completed connections per 1-second bin'));ax.legend(frameon=False,loc='upper right');ax.grid(axis='y',alpha=.18)
        ax.set_title(text('동시 부하 중 정책 검사와 배포 전환','Policy-gated deployment under concurrent load'),fontsize=15)
        fig.text(.5,.01,text(f"동시 클라이언트 4개 · {len(roll['rows']):,}회 연결 · 오류 {audit['rollout_failed']}회 · 관측한 서버 인증서로 서비스 구분",f"4 concurrent clients · {len(roll['rows']):,} connections · {audit['rollout_failed']} errors · Service identified by observed peer certificate"),ha='center',fontsize=10);fig.tight_layout(rect=[0,.04,1,1]);finish(fig,'04-rollout')
print(json.dumps(audit,indent=2))
