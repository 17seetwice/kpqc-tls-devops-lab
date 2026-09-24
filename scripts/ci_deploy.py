#!/usr/bin/env python3
"""GitHub-hosted runner -> two existing EC2 lab nodes; no permanent AWS keys."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request
from image_digest import config_digest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.aws-runtime/ci-state.json'

def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, **kwargs).stdout

def aws(*args):
    return json.loads(run(['aws', *args, '--region', 'ap-northeast-2', '--output', 'json']) or b'{}')

def save(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))

def ssh(host, role, command, **kwargs):
    return run(['ssh', '-i', str(ROOT/'kpqc-devops-lab.pem'), '-o', 'IdentitiesOnly=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlias=kpqc-'+role,
                '-o', 'UserKnownHostsFile='+str(ROOT/'.aws-runtime/known_hosts'),
                '-o', 'ConnectTimeout=10', 'ubuntu@'+host, command], **kwargs)

def cleanup():
    if not STATE.exists():
        return
    state = json.loads(STATE.read_text())
    errors = []
    for item in state.get('rules', []):
        try:
            aws('ec2', 'revoke-security-group-ingress', '--group-id', item['group'],
                '--ip-permissions', json.dumps(item['permission']))
        except subprocess.CalledProcessError as e:
            if b'InvalidPermission.NotFound' not in e.stderr:
                errors.append('Failed to remove runner SSH ingress')
    ids = state.get('started', [])
    if ids:
        try:
            aws('ec2', 'stop-instances', '--instance-ids', *ids)
            aws('ec2', 'wait', 'instance-stopped', '--instance-ids', *ids)
        except subprocess.CalledProcessError:
            errors.append('Failed to confirm stopped EC2 instances')
    state['cleanup_errors'] = errors
    state['cleanup_complete'] = not errors
    save(state)
    if errors:
        raise RuntimeError('; '.join(errors))

def deploy(image):
    ids = {r: os.environ['KPQC_'+r.upper()+'_INSTANCE_ID'] for r in ['server','client']}
    assert ids['server'] != ids['client']
    state = {'started': [], 'rules': [], 'commit': os.environ.get('GITHUB_SHA'),
             'run_url': os.environ.get('GITHUB_SERVER_URL','https://github.com')+'/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    save(state)
    response = aws('ec2', 'describe-instances', '--instance-ids', *ids.values())
    nodes = {i['InstanceId']: i for r in response['Reservations'] for i in r['Instances']}
    for node in nodes.values():
        assert {t['Key']:t['Value'] for t in node.get('Tags',[])}.get('Project') == 'kpqc-devops-lab'
        assert node['State']['Name'] == 'stopped', 'Start only stopped lab nodes; do not interrupt another experiment'
    assert len(nodes) == 2
    try:
        state['started'] = list(ids.values()); save(state)
        aws('ec2', 'start-instances', '--instance-ids', *state['started'])
        aws('ec2', 'wait', 'instance-status-ok', '--instance-ids', *state['started'])
        response = aws('ec2','describe-instances','--instance-ids',*state['started'])
        nodes = {i['InstanceId']:i for r in response['Reservations'] for i in r['Instances']}
        with urllib.request.urlopen('https://checkip.amazonaws.com', timeout=15) as res:
            cidr = str(ipaddress.IPv4Address(res.read().decode().strip()))+'/32'
        for role in ids:
            group = os.environ['KPQC_'+role.upper()+'_SG_ID']
            assert group in {s['GroupId'] for s in nodes[ids[role]]['SecurityGroups']}
            permission = [{'IpProtocol':'tcp','FromPort':22,'ToPort':22,
                           'IpRanges':[{'CidrIp':cidr,'Description':'kpqc-actions-'+os.environ.get('GITHUB_RUN_ID','local')}]}]
            # Persist intended cleanup before mutation, including interrupted requests.
            state['rules'].append({'group':group,'permission':permission}); save(state)
            aws('ec2','authorize-security-group-ingress','--group-id',group,'--ip-permissions',json.dumps(permission))
        archive = ROOT/'.aws-runtime/gate-image.tar'
        run(['docker','save','--output',str(archive),image])
        with archive.open('rb') as stream:
            image_id = config_digest(stream)
        digest_code = (ROOT/'scripts/image_digest.py').read_text()
        for role in ids:
            host = nodes[ids[role]]['PublicIpAddress']
            for attempt in range(30):
                try:
                    ssh(host,role,'true',timeout=15); break
                except subprocess.CalledProcessError:
                    time.sleep(3)
            else:
                raise RuntimeError('SSH not ready: '+role)
            with archive.open('rb') as stream:
                ssh(host,role,'sudo docker load',stdin=stream,timeout=300)
            remote_id = ssh(host,role,'sudo docker save '+shlex.quote(image)+' | python3 -c '+shlex.quote(digest_code),timeout=300).decode().strip()
            assert image_id == remote_id, 'Image identity mismatch'
        state['image_id'] = image_id
        state['image_identity_kind'] = 'sha256 of docker save image config (includes rootfs layer hashes)'
        save(state)
        subprocess.run(['python3','scripts/gate_suite.py','--server',nodes[ids['server']]['PublicIpAddress'],
                        '--client',nodes[ids['client']]['PublicIpAddress'], '--server-private',
                        nodes[ids['server']]['PrivateIpAddress'],'--image',image],check=True,cwd=ROOT)
    finally:
        cleanup()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup',action='store_true')
    parser.add_argument('--image',default='kpqc-lab:gate')
    args = parser.parse_args()
    cleanup() if args.cleanup else deploy(args.image)
