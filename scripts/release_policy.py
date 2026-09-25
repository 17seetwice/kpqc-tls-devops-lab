"""Recompute admission from every offered attempt, under a fixed lab SLO."""
#지연·실패율로 성능 기준 판단
import math
import time


def quantile(values, p=.95):
    xs=sorted(values)
    return xs[max(0,math.ceil(len(xs)*p)-1)] if xs else None


def summarize(window, policy, fingerprint):
    rows=window.get('rows',[])
    expected=round(policy['arrival_rate_per_second']*policy['window_seconds'])
    valid_ids=len(rows)==expected and sorted(r.get('sequence',-1) for r in rows)==list(range(expected))
    good=[r for r in rows if r.get('ok') is True and r.get('returncode')==0 and r.get('tls',{}).get('success') is True]
    bound=all(r.get('tls',{}).get('peer_certificate_sha256')==fingerprint for r in good)
    conform=all(r.get('tls',{}).get('group_code')==65056 and r['tls'].get('signature_code')==65408
                and r['tls'].get('verify_result')==0 and r['tls'].get('tls_version')=='TLSv1.3'
                and r['tls'].get('cipher')=='TLS_AES_256_GCM_SHA384' and not r['tls'].get('reused') for r in good)
    timings=all(isinstance(r.get('admission_ms'),(int,float)) and math.isfinite(r['admission_ms']) and r['admission_ms']>=0
                and isinstance(r.get('generator_lateness_ms'),(int,float)) and math.isfinite(r['generator_lateness_ms']) and r['generator_lateness_ms']>=0 for r in rows)
    if not timings:return {'passed':False,'reasons':['INVALID_TIMING_EVIDENCE']}
    p95=quantile([r['admission_ms'] for r in good]);late=quantile([r['generator_lateness_ms'] for r in rows])
    failures=(expected-len(good))/expected
    on_time=sum(r['admission_ms']<=policy['max_p95_admission_ms'] for r in good)/expected
    reasons=[]
    if not valid_ids:reasons.append('INCOMPLETE_OR_DUPLICATE_ATTEMPTS')
    if not bound or not conform:reasons.append('PERFORMANCE_TLS_BINDING_MISMATCH')
    if window.get('rate')!=policy['arrival_rate_per_second'] or window.get('seconds')!=policy['window_seconds']:reasons.append('LOAD_CONDITION_MISMATCH')
    if failures>policy['max_attempt_failure_fraction']:reasons.append('ATTEMPT_FAILURE_BUDGET_EXCEEDED')
    if on_time<policy['min_on_time_completion_fraction']:reasons.append('ON_TIME_COMPLETION_BUDGET_EXCEEDED')
    if p95 is None or p95>policy['max_p95_admission_ms']:reasons.append('P95_LATENCY_BUDGET_EXCEEDED')
    if late is None or late>policy['max_p95_generator_lateness_ms']:reasons.append('GENERATOR_TOO_LATE')
    return {'passed':not reasons,'reasons':reasons,'scheduled':expected,'successes':len(good),'failure_fraction':failures,
            'on_time_fraction':on_time,'p95_admission_ms':p95,'p95_generator_lateness_ms':late,
            'tls_p95_ms':quantile([r['tls']['handshake_ms'] for r in good])}


def evaluate(evidence,policy,candidate,now_ns=None):
    now_ns=time.time_ns() if now_ns is None else now_ns
    reasons=[];summaries=[]
    if not isinstance(evidence,dict) or evidence.get('binding')!=candidate:
        return {'passed':False,'reasons':['PERFORMANCE_CANDIDATE_MISMATCH'],'windows':[]}
    windows=evidence.get('windows',[])
    if not isinstance(windows,list) or len(windows)!=policy['required_windows']:
        return {'passed':False,'reasons':['MISSING_PERFORMANCE_WINDOWS'],'windows':[]}
    if len({w.get('tag') for w in windows})!=len(windows):reasons.append('DUPLICATE_PERFORMANCE_WINDOWS')
    for window in windows:
        try:
            end=window['observed_at_ns']
            if not candidate['created_at_ns']<=end<=now_ns or now_ns-end>policy['max_evidence_age_seconds']*1e9:reasons.append('STALE_PERFORMANCE_EVIDENCE')
            s=summarize(window,policy,candidate['certificate_sha256'])
        except (KeyError,TypeError,ValueError,ZeroDivisionError):
            s={'passed':False,'reasons':['INVALID_PERFORMANCE_EVIDENCE']}
        summaries.append(s);reasons.extend(s['reasons'])
    return {'passed':not reasons,'reasons':list(dict.fromkeys(reasons)),'windows':summaries,'policy_version':policy['version']}
