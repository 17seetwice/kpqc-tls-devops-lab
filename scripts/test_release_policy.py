"""Admission must reject missing, stale, misbound or overloaded observations."""
import copy,json,time,unittest
from pathlib import Path
from release_policy import evaluate

class ReleasePolicyTests(unittest.TestCase):
    def setUp(self):
        self.p=json.loads((Path(__file__).resolve().parents[1]/'policies/release-slo.json').read_text())
        self.now=time.time_ns();self.c={'created_at_ns':self.now-2_000_000_000,'certificate_sha256':'approved'}
        tls={'success':True,'peer_certificate_sha256':'approved','group_code':65056,'signature_code':65408,'verify_result':0,'tls_version':'TLSv1.3','cipher':'TLS_AES_256_GCM_SHA384','reused':False,'handshake_ms':4}
        rows=[{'sequence':i,'ok':True,'returncode':0,'admission_ms':10,'generator_lateness_ms':1,'tls':dict(tls)} for i in range(100)]
        self.ev={'binding':self.c,'windows':[{'tag':str(i),'rate':10,'seconds':10,'observed_at_ns':self.now-1_000_000_000,'rows':copy.deepcopy(rows)} for i in range(3)]}
    def result(self):return evaluate(self.ev,self.p,self.c,self.now)
    def test_healthy(self):self.assertTrue(self.result()['passed'])
    def test_slow_valid_crypto(self):
        for r in self.ev['windows'][0]['rows']:r['admission_ms']=350
        self.assertIn('P95_LATENCY_BUDGET_EXCEEDED',self.result()['reasons'])
    def test_missing_and_duplicate_attempts(self):
        self.ev['windows'][0]['rows'][0]['sequence']=1
        self.assertFalse(self.result()['passed'])
    def test_timeout_in_denominator(self):
        for r in self.ev['windows'][0]['rows'][:2]:r.update(ok=False,tls={})
        self.assertIn('ATTEMPT_FAILURE_BUDGET_EXCEEDED',self.result()['reasons'])
    def test_stale_and_wrong_candidate(self):
        self.ev['windows'][0]['observed_at_ns']=self.now-301_000_000_000
        self.assertFalse(self.result()['passed'])
        self.ev['binding']={};self.assertIn('PERFORMANCE_CANDIDATE_MISMATCH',self.result()['reasons'])
    def test_certificate_and_classical_mismatch(self):
        self.ev['windows'][0]['rows'][0]['tls']['group_code']=29
        self.assertIn('PERFORMANCE_TLS_BINDING_MISMATCH',self.result()['reasons'])
    def test_generator_lateness_is_not_service_success(self):
        for r in self.ev['windows'][0]['rows']:r['generator_lateness_ms']=60
        self.assertIn('GENERATOR_TOO_LATE',self.result()['reasons'])
    def test_no_evidence_and_nonfinite(self):
        self.assertFalse(evaluate(None,self.p,self.c,self.now)['passed'])
        self.ev['windows'][0]['rows'][0]['admission_ms']=float('nan')
        self.assertFalse(self.result()['passed'])

if __name__=='__main__':unittest.main()
