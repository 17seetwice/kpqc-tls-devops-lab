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

# 읽는 순서: deploy()가 전체 흐름, cleanup()이 성공·실패 후 자원 정리를 담당한다.
# GitHub는 실행 제어만 담당하고, TLS 트래픽은 AWS 서버·클라이언트 사이에서 흐른다.
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.aws-runtime/ci-state.json'

def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, **kwargs).stdout

# AWS CLI는 워크플로가 OIDC로 받은 단기 인증을 사용한다. 영구 AWS 키를 코드에 넣지 않는다.
def aws(*args):
    return json.loads(run(['aws', *args, '--region', 'ap-northeast-2', '--output', 'json']) or b'{}')

# 중간 상태를 파일로 남겨 별도의 always() 정리 단계에서도 시작한 자원과 규칙을 찾는다.
def save(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))

# 호스트 키를 미리 검증한 값과 비교한다. IP가 바뀌어도 고정 별칭으로 같은 EC2인지 확인한다.
def ssh(host, role, command, **kwargs):
    return run(['ssh', '-i', str(ROOT/'kpqc-devops-lab.pem'), '-o', 'IdentitiesOnly=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlias=kpqc-'+role,
                '-o', 'UserKnownHostsFile='+str(ROOT/'.aws-runtime/known_hosts'),
                '-o', 'ConnectTimeout=10', 'ubuntu@'+host, command], **kwargs)

# 우리 실행에서 추가한 SSH 규칙과 시작한 EC2만 정리한다. EBS 삭제나 인스턴스 종료는 하지 않는다.
# 규칙 제거가 실패해도 EC2 중지를 시도하고, 정리 실패를 성공으로 숨기지 않는다.
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

def deploy(image, extended=False):
    # Secret에 등록한 서버·클라이언트 ID를 읽는다. 기존 프로젝트의 다른 인스턴스를 검색해 선택하지 않는다.
    ids = {r: os.environ['KPQC_'+r.upper()+'_INSTANCE_ID'] for r in ['server','client']}
    assert ids['server'] != ids['client']
    state = {'started': [], 'rules': [], 'commit': os.environ.get('GITHUB_SHA'),
             'run_url': os.environ.get('GITHUB_SERVER_URL','https://github.com')+'/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    save(state)
    response = aws('ec2', 'describe-instances', '--instance-ids', *ids.values())
    nodes = {i['InstanceId']: i for r in response['Reservations'] for i in r['Instances']}
    # 실험 태그와 stopped 상태를 확인한다. 이미 실행 중이면 다른 작업일 수 있으므로 중단한다.
    for node in nodes.values():
        assert {t['Key']:t['Value'] for t in node.get('Tags',[])}.get('Project') == 'kpqc-devops-lab'
        assert node['State']['Name'] == 'stopped', 'Start only stopped lab nodes; do not interrupt another experiment'
    assert len(nodes) == 2
    try:
        # 시작 요청 전에 ID를 기록해, 요청 도중 예외가 나도 finally에서 정리할 수 있게 한다.
        state['started'] = list(ids.values()); save(state)
        aws('ec2', 'start-instances', '--instance-ids', *state['started'])
        aws('ec2', 'wait', 'instance-status-ok', '--instance-ids', *state['started'])
        response = aws('ec2','describe-instances','--instance-ids',*state['started'])
        nodes = {i['InstanceId']:i for r in response['Reservations'] for i in r['Instances']}
        # GitHub runner의 현재 공인 IPv4 하나만 임시 SSH 소스로 사용한다. TLS 4433 규칙은 건드리지 않는다.
        with urllib.request.urlopen('https://checkip.amazonaws.com', timeout=15) as res:
            cidr = str(ipaddress.IPv4Address(res.read().decode().strip()))+'/32'
        for role in ids:
            group = os.environ['KPQC_'+role.upper()+'_SG_ID']
            assert group in {s['GroupId'] for s in nodes[ids[role]]['SecurityGroups']}
            permission = [{'IpProtocol':'tcp','FromPort':22,'ToPort':22,
                           'IpRanges':[{'CidrIp':cidr,'Description':'kpqc-actions-'+os.environ.get('GITHUB_RUN_ID','local')}]}]
            # Persist intended cleanup before mutation, including interrupted requests.
            state['rules'].append({'group':group,'permission':permission}); save(state)
            try:
                aws('ec2','authorize-security-group-ingress','--group-id',group,'--ip-permissions',json.dumps(permission))
            except subprocess.CalledProcessError as e:
                if b'InvalidPermission.Duplicate' in e.stderr:
                    state['rules'].pop()
                    state.setdefault('reused_ssh_groups',[]).append(group);save(state)
                else:
                    raise

        # 한 번 빌드하고 사전 시험한 이미지를 저장해 두 EC2에 그대로 전달한다. EC2에서 재빌드하지 않는다.
        archive = ROOT/'.aws-runtime/gate-image.tar'
        run(['docker','save','--output',str(archive),image])
        # Docker 저장 방식별 inspect ID 차이를 피하고, 실행 설정·계층 해시를 담은 config의 SHA-256을 비교한다.
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
        os.environ['KPQC_IMAGE_ID']=image_id
        # 실제 후보 승인·차단은 gate_suite.py가 수행한다. 제어는 SSH, TLS 접속은 사설 IP를 사용한다.
        subprocess.run(['python3','scripts/gate_suite.py','--server',nodes[ids['server']]['PublicIpAddress'],
                        '--client',nodes[ids['client']]['PublicIpAddress'], '--server-private',
                        nodes[ids['server']]['PrivateIpAddress'],'--image',image],check=True,cwd=ROOT)
        if extended:
            subprocess.run(['python3','scripts/extended_handshake.py','--server',nodes[ids['server']]['PublicIpAddress'],
                            '--client',nodes[ids['client']]['PublicIpAddress'],'--server-private',nodes[ids['server']]['PrivateIpAddress'],
                            '--image',image,*(['--balanced'] if os.environ.get('KPQC_BALANCED_LATENCY')=='1' else [])],check=True,cwd=ROOT)
    # 시험 성공뿐 아니라 중간 실패에도 정리한다. 강제 종료/API 장애 시에는 별도 정리 단계와 상태 확인이 필요하다.
    finally:
        cleanup()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup',action='store_true')
    parser.add_argument('--image',default='kpqc-lab:gate')
    parser.add_argument('--extended',action='store_true')
    args = parser.parse_args()
    cleanup() if args.cleanup else deploy(args.image,args.extended)
