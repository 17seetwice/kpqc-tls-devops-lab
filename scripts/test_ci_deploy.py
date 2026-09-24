"""Failure-path checks: protect pre-existing workloads and clean partial starts."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import ci_deploy


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)/'ci-state.json'
        self.patcher = patch.object(ci_deploy, 'STATE', self.state)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_running_nodes_are_not_stopped(self):
        response = {'Reservations':[{'Instances':[
            {'InstanceId':i,'State':{'Name':'running'},'Tags':[{'Key':'Project','Value':'kpqc-devops-lab'}]}
            for i in ['server-id','client-id']]}]}
        with patch.dict(ci_deploy.os.environ, {'KPQC_SERVER_INSTANCE_ID':'server-id','KPQC_CLIENT_INSTANCE_ID':'client-id'}), patch.object(ci_deploy, 'aws', return_value=response) as aws:
            with self.assertRaises(AssertionError):
                ci_deploy.deploy('test-image')
            self.assertEqual(aws.call_count, 1)
            self.assertEqual(json.loads(self.state.read_text())['started'], [])

    def test_partial_start_failure_stops_owned_nodes(self):
        response = {'Reservations':[{'Instances':[
            {'InstanceId':i,'State':{'Name':'stopped'},'Tags':[{'Key':'Project','Value':'kpqc-devops-lab'}]}
            for i in ['server-id','client-id']]}]}
        calls = []
        def aws(*args):
            calls.append(args)
            if args[1] == 'describe-instances':
                return response
            if args[1] == 'start-instances':
                raise subprocess.CalledProcessError(1, 'aws', stderr=b'simulated partial start')
            return {}
        with patch.dict(ci_deploy.os.environ, {'KPQC_SERVER_INSTANCE_ID':'server-id','KPQC_CLIENT_INSTANCE_ID':'client-id'}), patch.object(ci_deploy,'aws', side_effect=aws):
            with self.assertRaises(subprocess.CalledProcessError):
                ci_deploy.deploy('test-image')
        self.assertIn(('ec2','stop-instances','--instance-ids','server-id','client-id'), calls)
        self.assertTrue(json.loads(self.state.read_text())['cleanup_complete'])

    def test_revoke_failure_still_stops_nodes_and_fails_cleanup(self):
        ci_deploy.save({'started':['server-id'], 'rules':[{'group':'sg-test','permission':[]}]})
        def aws(*args):
            if args[1] == 'revoke-security-group-ingress':
                raise subprocess.CalledProcessError(1, 'aws', stderr=b'AccessDenied')
            return {}
        with patch.object(ci_deploy,'aws',side_effect=aws) as mock:
            with self.assertRaises(RuntimeError):
                ci_deploy.cleanup()
            self.assertTrue(any(call.args[1] == 'stop-instances' for call in mock.call_args_list))
        self.assertFalse(json.loads(self.state.read_text())['cleanup_complete'])

    def test_already_removed_rule_is_idempotent(self):
        ci_deploy.save({'started':[], 'rules':[{'group':'sg-test','permission':[]}]})
        with patch.object(ci_deploy,'aws', side_effect=subprocess.CalledProcessError(1, 'aws', stderr=b'InvalidPermission.NotFound')):
            ci_deploy.cleanup()
        self.assertTrue(json.loads(self.state.read_text())['cleanup_complete'])


if __name__ == '__main__':
    unittest.main()
