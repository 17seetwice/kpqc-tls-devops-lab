#!/usr/bin/env python3
"""Generate bilingual offline review reports from audited release evidence."""
import argparse,hashlib,json,statistics
from pathlib import Path
import markdown
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
p=argparse.ArgumentParser();p.add_argument('folder');a=p.parse_args();P=Path(a.folder)
D=json.loads((P/'measurements.public.json').read_text());A=json.loads((P/'audit.json').read_text());W=json.loads((P/'workflow.public.json').read_text());C=json.loads((P/'cleanup-verification.json').read_text())
assert A['status']=='passed' and A['source_commit']==W['commit'] and A['image_identity']==W['deployment']['image_id']
assert W['deployment']['cleanup_complete'] and not W['deployment']['cleanup_errors']
assert C['cleanup_complete']
if 'instances' in C: assert len(C['instances'])==2 and all(x['State']=='stopped' for x in C['instances'])
url=W['deployment']['run_url']
for lang in ['ko','en']:
 ko=lang=='ko';folder=P/lang;folder.mkdir(exist_ok=True)
 plt.rcParams.update({'font.family':'Apple SD Gothic Neo' if ko else 'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False,'axes.unicode_minus':False,'svg.fonttype':'none'})
 names=['지연 주입 후보','최초 KPQC 배포 후보','후속 업데이트 후보'] if ko else ['Injected-delay candidate','Initial KPQC candidate','Subsequent update candidate']
 fig,axes=plt.subplots(1,2,figsize=(11,4.7))
 for j,(field,title) in enumerate([('p95_admission_ms_by_window','접속 시도 완료 지연' if ko else 'Scheduled-arrival to completion'),('p95_tls_ms_by_window','TLS 핸드셰이크 지연' if ko else 'TLS handshake latency')]):
  ax=axes[j]
  for i,c in enumerate(A['candidate_summary']):
   vals=c[field];ax.bar(i,statistics.median(vals),color=['#D55E00','#0072B2','#009E73'][i],alpha=.8,width=.55)
   ax.scatter(np.linspace(i-.12,i+.12,len(vals)),vals,facecolors='white',edgecolors='#182b3a',zorder=3,s=40)
  if j==0:ax.axhline(200,color='#222',linestyle='--',label='SLO: 200 ms');ax.legend(frameon=False)
  ax.set_xticks(range(3),names,rotation=10);ax.set_ylabel('p95 (ms)');ax.set_title(title);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
 fig.suptitle('암호 적합성과 성능 승인 조건의 분리' if ko else 'Cryptographic compliance and performance admission',fontsize=15)
 fig.text(.5,.01,'점: 측정 구간별 p95 · 막대: 세 구간 p95의 중앙값' if ko else 'Points: per-window p95 · Bars: median of three window p95 values',ha='center',fontsize=10)
 fig.tight_layout(rect=[0,.06,1,.93])
 for ext in ['png','svg']:fig.savefig(folder/f'01-admission.{ext}',dpi=180,bbox_inches='tight')
 plt.close(fig)
 rows=D['recovery_traffic']['rows'];start=D['recovery_traffic']['start_ns'];f=D['certificate_sha256'];bins=np.arange(0,16)
 fig,ax=plt.subplots(figsize=(11,4.5));bottom=np.zeros(15)
 kinds=[('v3','#0072B2','신규 배포 서비스' if ko else 'New deployment'),('failed','#D55E00','실패 접속' if ko else 'Failed attempts'),('v2','#009E73','복구된 이전 서비스' if ko else 'Restored previous deployment')]
 for kind,color,label in kinds:
  selected=[r for r in rows if (not r['ok'] if kind=='failed' else r['ok'] and r['tls']['peer_certificate_sha256']==f['good-'+kind])]
  values=np.histogram([(r['scheduled_ns']-start)/1e9 for r in selected],bins=bins)[0]
  ax.bar(bins[:-1],values,bottom=bottom,width=.9,align='edge',color=color,label=label);bottom+=values
 ax.set_xlabel('부하 시작 후 예정 도착 시각 (s)' if ko else 'Scheduled arrival after load start (s)')
 ax.set_ylabel('접속 시도 / 1초 구간' if ko else 'Attempts / one-second bin');ax.set_ylim(0,14);ax.set_xticks([0,3,6,9,12,15]);ax.legend(ncol=3,frameon=False,loc='upper center');ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
 ax.set_title('장애 주입과 이전 KPQC 버전으로의 자동 복구' if ko else 'Injected failure and automatic recovery to approved KPQC')
 fig.tight_layout()
 for ext in ['png','svg']:fig.savefig(folder/f'02-recovery.{ext}',dpi=180,bbox_inches='tight')
 plt.close(fig)
 table=''
 for name,c in zip(names,A['candidate_summary']):
  table+='| '+name+' | '+('통과' if ko else 'Pass')+' | '+('승인' if c['admitted'] and ko else '거절' if ko else 'Admit' if c['admitted'] else 'Reject')+' | '+', '.join(f'{x:.2f}' for x in c['p95_admission_ms_by_window'])+' |\n'
 if ko:
  body=f'''# KPQC 전환·성능 승인·장애 복구

[English](README.en.html) · [그림 모음](gallery.html) · [원자료](measurements.public.json) · [검증 요약](audit.json)

기존 TLS 성능 측정과 암호 정책 게이트를 연결해 **레거시 서비스에서 KPQC로의 전환 → 성능 기반 배포 승인 → 장애 시 이전 승인 KPQC 버전 복구**를 검증했다. [GitHub Actions 실행]({url}), 소스 `{A['source_commit'][:7]}`. {A['assertions']}개 검증 항목 통과. 워크플로는 기존 두 EC2의 중지 완료와 임시 SSH 규칙 제거를 확인했다.

## 실행 환경과 승인 정책

![배포 수명주기](architecture.ko.png)

서울 동일 가용 영역의 m7i.large 서버·클라이언트 두 대, 컨테이너별 2 CPU/512 MiB, MTU (Maximum Transmission Unit) 1500의 Docker 브리지 환경이다. 초기 서비스는 X25519 + ECDSA P-256, KPQC 후보는 SMAUG1 + HAETAE2다. 최초 KPQC 배포와 후속 업데이트는 동일 암호 조합을 사용하며, 서로 다른 인증서와 서버 프로세스로 구분한다. TLS (Transport Layer Security) 1.3의 전체 핸드셰이크를 사용하며, 직접 신뢰한 서버 인증서와 사전 준비된 전환 가능 클라이언트를 사용한다.

SLO (Service Level Objective)는 시험 전에 고정한 **모의 서비스 목표**다. 후보마다 초당 10회, 10초 × 3구간의 고정 도착률로 시험한다. 각 구간에서 실패율≤1%, 200ms 내 성공 비율≥99%, 성공 접속 완료 지연 p95 ≤200 ms를 요구한다. 부하 생성 지연 p95가 50ms를 초과하거나 증적이 누락되면 승인하지 않는다.

접속 완료 지연은 예정 도착부터 C 클라이언트 종료까지이며, 스케줄 대기·프로세스 초기화·TCP·준비 신호·TLS·종료를 포함한다. 별도 기록한 순수 TLS 지연은 `SSL_connect` 호출 구간이다. HTTP와 업무 거래는 포함하지 않는다. 두 지표를 같은 것으로 해석하지 않는다.

## 배포 후보의 역할과 실험 순서

**최초 KPQC 배포 후보**는 기존 X25519 + ECDSA P-256 서비스를 SMAUG1 + HAETAE2 서비스로 전환하기 위한 배포 대상이다. 암호·인증서 검증과 성능 기준을 통과하면 기존 서비스를 대체한다.

**후속 업데이트 후보**는 KPQC 도입 이후의 서비스 갱신을 모사한다. 동일한 SMAUG1 + HAETAE2를 사용하되 새로운 서버 인증서와 별도 서버 프로세스로 배포한다. 이번 실험에서 변경하는 것은 인증서와 배포 대상이며, 암호 알고리즘과 업무 기능은 변경하지 않는다.

후속 업데이트를 승인·배포한 다음 신규 배포 서비스에 장애를 주입한다. 최초 KPQC 배포로 승인받은 서비스가 이때의 **이전 승인 서비스**다. 해당 서비스의 현재 TLS 연결·인증서·암호 정책을 확인한 뒤 연결 경로를 복구한다. 두 단계는 **KPQC 최초 도입**과 **도입 후 갱신·장애 복구**를 각각 검증하며, 복구 후에도 KPQC 구성을 유지한다.

## 후보 승인 결과

모든 후보의 암호 검사는 통과했다. 지연 주입 후보에는 서버의 TLS 처리 시작 전 350ms 대기를 의도적으로 넣었다. 이는 성능 회귀 검출 시험이며 PQC 알고리즘의 본래 성능이 아니다. 아래 각 값은 100개 예정 시도의 한 측정 구간에서 구한 성공 접속 완료 지연 p95(ms)다.

| 후보 | 암호 검사 | 최종 승인 | 세 구간 p95(ms) |
|---|---|---|---|
{table}
![후보 성능 승인](ko/01-admission.png)

지연 후보의 승격 요청은 거절되고 기존 레거시 서비스가 유지됐다. 최초 KPQC 배포 후보의 승인 후 실제 서버 인증서와 협상 코드가 KPQC로 바뀌었으며, 이어서 후속 업데이트 후보도 승인됐다. 성능 측정 증적은 후보 세대·인증서·정책 식별자와 연결하고 승인 시 다시 판정한다.

## 장애 복구 결과

신규 배포 서비스의 서버 프로세스 그룹을 중단한 뒤, 상태 관측에서 연속 두 번 실패하면 이전 승인 서비스의 현재 접속·인증서·승인 이력을 확인해 자동 복구했다. 고전 버전, 다른 인증서, 오래된 복구 증적은 거절했다.

- 장애 주입 요청부터 감지: **{A['detection_ms']/1000:.3f}초**.
- 장애 주입 요청부터 첫 복구 성공 확인: **{A['recovery_ms']/1000:.3f}초** (사전 목표10초).
- 장애 관측 부하:150회 중 실패 **{A['recovery_failures']}회**, 신규 배포 서비스 성공 {A['old_pqc_successes']}회, 복구된 이전 서비스 성공 {A['restored_pqc_successes']}회.
- 마지막20개 접속은 모두 이전 승인 서비스로 연결됐고, 복구 후 암호 정책과 고전 접속 거절을 재검증했다.

![자동 복구](ko/02-recovery.png)

복구 시간은 제어기의 동일 단조 시계로 측정하며 SSH 제어 왕복 시간을 포함한다. 장애 기간의 실패를 숨기지 않으며 무중단 결과로 표현하지 않는다. 기존 TCP 세션이나 금융 거래의 보존을 검증한 것은 아니다.

## 구현 개선과 검토

기존 서버의 유휴 `accept` 시간 초과 시 작업자가 종료되던 문제를 수정했다. 17초 유휴 후 작업자8개와 정상 접속을 확인했고, 승인된 이전 서비스는 다음 후보 측정 동안에도 복구 대상으로 유지했다.

Mac amd64 에뮬레이션 전체 시험에서는 정상 후보의 100개 중2개가200ms를 넘어서 성능 게이트가 거절한 기록도 보존했다. 기준을 완화하지 않고 네이티브 Linux 전체 사전시험 및 AWS 시험을 분리했다. 수치는 이번 AWS 실행에 한정한다.

이 실험은 제한된 부하에서 승인·거절과 복구 경로의 기능을 보여준다. 최대 처리량·금융 업무 SLO·장기간 운영 가용성·자동 코드 변환을 입증하지 않는다. 고전→KPQC 전환과 이후 신규 배포 서비스에서 이전 승인 서비스로의 복구를 구분하며, 전환 후 고전 서비스로 복귀하지 않는다.

[워크플로 증적](workflow.public.json) · [정리 확인](cleanup-verification.json) · [실험 계획](../../docs/RELEASE_EXPERIMENT_PLAN.md)
'''
 else:
  body=f'''# KPQC migration, performance admission and recovery

[한국어](README.html) · [Gallery](gallery.html) · [Raw evidence](measurements.public.json) · [Audit](audit.json)

The existing TLS measurement and cryptographic gate now form one lifecycle: **classical-to-KPQC migration, performance admission, and automatic recovery to an approved KPQC version**. [GitHub Actions execution]({url}), source `{A['source_commit'][:7]}`; {A['assertions']} assertions passed. The workflow confirmed that both existing EC2 instances stopped and temporary SSH ingress was removed.

## Environment and preregistered target

![Release lifecycle](architecture.en.png)

Two m7i.large instances in the same Seoul availability zone; each container has 2 CPUs/512 MiB, a Docker bridge and MTU (Maximum Transmission Unit) 1500. The original service uses X25519 + ECDSA P-256; candidates use SMAUG1 + HAETAE2. The initial KPQC release and subsequent update use the same algorithms, with distinct certificates and server processes. Full TLS (Transport Layer Security) 1.3 handshakes, directly trusted server certificates and migration-capable clients are assumed.

The SLO (Service Level Objective) is a **synthetic service target**, fixed before testing. Each candidate receives 10 scheduled arrivals/s for three 10-second windows. Every window must have ≤1% failed attempts, ≥99% successful completions within 200 ms, and successful completion p95 ≤200 ms. Generator-lateness p95 >50 ms or incomplete evidence prevents admission.

Completion latency runs from scheduled arrival to C-client process exit, including scheduling, initialization, TCP, readiness, TLS and teardown. Separately recorded TLS latency covers only `SSL_connect`. There is no HTTP or business transaction. Every scheduled attempt remains in the denominator.

## Deployment roles and experiment sequence

The **initial KPQC deployment candidate** replaces the existing X25519 + ECDSA P-256 service with SMAUG1 + HAETAE2. It replaces the active service only after passing cryptographic, certificate and performance checks.

The **subsequent update candidate** models a service update after KPQC adoption. It retains SMAUG1 + HAETAE2 and uses a new server certificate and a separate server process. This experiment changes the certificate and deployment target; it does not change the cryptographic algorithms or business functionality.

After approving and deploying the update, the experiment injects a failure into the newly deployed service. The service accepted during initial KPQC deployment is now the **previously approved service**. Its current TLS connectivity, certificate and cryptographic policy are checked before routing connections back to it. The two stages test **initial KPQC adoption** and **subsequent update and recovery**, respectively, while retaining KPQC after recovery.

## Candidate admission

All candidates passed cryptographic checks. The faulted candidate intentionally waits 350 ms before server TLS processing. This validates regression detection and is not intrinsic KPQC cost. Each value below is successful completion p95(ms) from one 100-arrival window.

| Candidate | Crypto check | Final decision | Three window p95 values(ms) |
|---|---|---|---|
{table}
![Performance admission](en/01-admission.png)

The slow candidate could not be promoted; the classical service remained active. The approved initial KPQC release then replaced it, verified through the actual certificate and negotiated codes. The subsequent update was also admitted. Performance evidence is bound to the candidate generation, certificate and policy and re-evaluated at promotion.

## Failure and automatic recovery

After terminating the newly deployed server process group, two consecutive failed health observations trigger validation and restoration of the previously approved deployment. Classical targets, incorrect certificates and stale health evidence are rejected.

- Injection request to detection: **{A['detection_ms']/1000:.3f}s**.
- Injection request to first verified recovery: **{A['recovery_ms']/1000:.3f}s**, against a 10-second target.
- 150 scheduled fault-window attempts: **{A['recovery_failures']} failures**, {A['old_pqc_successes']} successful connections to the new deployment, {A['restored_pqc_successes']} successful connections to the restored previous deployment.
- The final 20 attempts succeeded on the restored previous deployment; cryptographic policy and prohibited-client rejection were checked again.

![Automatic recovery](en/02-recovery.png)

Recovery uses one controller monotonic clock and includes SSH control round trips. Failed attempts are retained. This is not a zero-downtime or transaction-preservation claim.

## Implementation and scope

Idle accept-timeout exits in the prefork server were fixed; all eight workers and a successful connection were checked after 17 seconds idle. The former approved service stayed available while the next candidate was measured.

An earlier full Mac amd64-emulation trial rejected a healthy candidate because 2/100 attempts exceeded 200 ms. That failed trial is preserved; the target was not relaxed. Native Linux preflight and AWS execution are separate. These figures describe only the AWS execution.

This bounded trial validates admission and recovery, not maximum capacity, banking-service SLOs, long-term availability or automatic source-code migration. Initial classical-to-KPQC migration and subsequent recovery to the previously approved KPQC deployment are distinct. No classical rollback is allowed after migration.

[Workflow evidence](workflow.public.json) · [Cleanup verification](cleanup-verification.json) · [Plan](../../docs/RELEASE_EXPERIMENT_PLAN.md)
'''
 name='README' if ko else 'README.en';(P/(name+'.md')).write_text(body,encoding='utf-8')
 content=markdown.markdown(body,extensions=['tables','fenced_code'])
 css='body{max-width:1100px;margin:32px auto;padding:0 24px;font:16px/1.75 system-ui;color:#182b3a}img{max-width:100%}table{border-collapse:collapse;display:block;overflow:auto}th,td{border:1px solid #ccd5dc;padding:8px}a{color:#006da8}pre{overflow:auto}h1{line-height:1.4}'
 (P/(name+'.html')).write_text(f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KPQC release lifecycle</title><style>{css}</style>{content}</html>',encoding='utf-8')
gallery='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KPQC release figures</title><style>body{max-width:1150px;margin:32px auto;padding:24px;font:16px/1.7 system-ui}img{max-width:100%}a{margin-right:20px}</style><h1>KPQC 전환·성능 승인·장애 복구</h1><nav><a href="README.html">한국어 보고서</a><a href="README.en.html">English report</a></nav>'
for lang in ['ko','en']:
 gallery+=f'<h2>{"한국어" if lang=="ko" else "English"}</h2>'
 gallery+=f'<img src="architecture.{lang}.png" alt="Release lifecycle"><p><a href="architecture.{lang}.svg">SVG</a></p>'
 for fig in ['01-admission','02-recovery']:gallery+=f'<img src="{lang}/{fig}.png" alt="{fig}"><p><a href="{lang}/{fig}.svg">SVG</a></p>'
(P/'gallery.html').write_text(gallery+'</html>',encoding='utf-8')
files=sorted(f for f in P.rglob('*') if f.is_file() and f.name!='SHA256SUMS');(P/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(P))+'\n' for f in files))
print('Generated bilingual release report and figures:',P)
