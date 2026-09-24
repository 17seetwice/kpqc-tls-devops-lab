#!/usr/bin/env python3
"""Export only allowlisted deployment evidence to public GitHub artifacts."""
import json
from pathlib import Path
import os

# GitHub 공개 artifact에 올릴 필드만 선택한다. 개인키·AWS 식별자·원문 SSH 설정은 포함하지 않는다.
root = Path(__file__).resolve().parents[1]
out = root/'public-evidence'
out.mkdir(exist_ok=True)
summary = {'commit':os.environ.get('GITHUB_SHA'), 'run_id':os.environ.get('GITHUB_RUN_ID'), 'runs':[]}
# 파일 전환 실험의 판정 목록과 배포 게이트 결과를 별도로 보존한다.
summary['file_experiments'] = []
for path in sorted((root/'artifacts').glob('*/results.json')):
    if 'gate-' in path.parent.name:
        continue
    data = json.loads(path.read_text())
    summary['file_experiments'].append({'run_id':path.parent.name,'status':data.get('status'),
                                      'assertions':data.get('tests',data.get('assertions',[]))})
for path in sorted((root/'artifacts').glob('*gate-*/results.json')):
    data = json.loads(path.read_text())
    summary['runs'].append({
        'run_id':data['run_id'], 'status':data['status'],
        'assertions':data['assertions'], 'monitor':data.get('monitor'),
        'scenarios':[{'candidate':s['candidate'], 'decision':s['decision'],
                      'required_legacy_decision':s.get('required_legacy_decision')} for s in data['scenarios']],
        'promoted_version':data.get('promotion',{}).get('active',{}).get('version'),
    })
# 이미지 식별자·커밋·정리 성공 여부를 남겨 어떤 코드와 이미지로 실행했는지 추적한다.
state = root/'.aws-runtime/ci-state.json'
if state.exists():
    data = json.loads(state.read_text())
    summary['deployment'] = {k:data.get(k) for k in ['commit','run_url','image_id','image_identity_kind','cleanup_complete','cleanup_errors']}
(out/'summary.json').write_text(json.dumps(summary,indent=2))
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:
        stream.write('## PQC deployment gate evidence\n\n')
        for run in summary['runs']:
            stream.write(f"- {run['run_id']}: **{run['status']}**, {sum(a['passed'] for a in run['assertions'])}/{len(run['assertions'])} assertions\n")
            for s in run['scenarios']:
                stream.write(f"  - {s['candidate']}: {s['decision']}\n")
        if 'deployment' in summary:
            stream.write(f"\nCleanup complete: {summary['deployment']['cleanup_complete']}\n")
