"""Regression tests: evidence must establish policy compliance, not mere reachability."""
import copy,json,unittest
from pathlib import Path
from gate_policy import evaluate
P=json.loads((Path(__file__).resolve().parents[1]/'policies/pqc-required.json').read_text())
class PolicyTests(unittest.TestCase):
    def setUp(self):
        good=dict(success=True,returncode=0,verify_result=0,tls_version='TLSv1.3',group_code=65056,signature_code=65408,cipher='TLS_AES_256_GCM_SHA384')
        reject=dict(success=False,returncode=1,ssl_error=1,verify_result=0,handshake_messages=1)
        self.q=dict(ready=True,probes={**{c:dict(good) for c in P['required_clients']},**{c:dict(reject) for c in P['forbidden_clients']}})
    def test_valid(self): self.assertTrue(evaluate(self.q,P)['deployment_allowed'])
    def test_each_forbidden_client(self):
        for client in P['forbidden_clients']:
            with self.subTest(client=client):
                q=copy.deepcopy(self.q);q['probes'][client]['success']=True
                self.assertIn('PROHIBITED_TLS_VERSION_ACCEPTED' if client=='tls12' else 'CLASSICAL_FALLBACK_ACCEPTED',evaluate(q,P)['reasons'])
    def test_missing_or_broken_or_timeout(self):
        for client in self.q['probes']:
            for value in (None,{},dict(success=False,probe_error='timeout'),dict(success=False,transport_errors=['connection refused'])):
                with self.subTest(client=client,value=value):
                    q=copy.deepcopy(self.q);q['probes'][client]=value
                    self.assertFalse(evaluate(q,P)['deployment_allowed'])
    def test_cannot_remove_mandatory_clients(self):
        self.q['required_clients']=[];del self.q['probes']['pqc']
        self.assertFalse(evaluate(self.q,P)['deployment_allowed'])
    def test_untrusted_certificate_is_not_negative_success(self):
        self.q['probes']['classical_kem']['verify_result']=18
        self.assertFalse(evaluate(self.q,P)['deployment_allowed'])
    def test_not_ready(self):
        self.q['ready']=False
        self.assertFalse(evaluate(self.q,P)['deployment_allowed'])
if __name__=='__main__':unittest.main()
