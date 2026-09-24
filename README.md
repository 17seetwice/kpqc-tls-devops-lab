# kpqc-tls-devops-lab

KPQC TLS migration PoC with automated deployment gates and AWS EC2 validation.

국산 양자내성암호 OpenSSL 이미지로 TLS 협상과 전자서명 전환을 검증하는 실험이다.
SMAUG-T·NTRU+ KEM과 HAETAE·AIMer 서명을 대상으로 한다.

## 실행

```sh
docker compose run --build --rm lab
docker compose -f compose.gate.yaml run --build --rm gate
```

Docker amd64 이미지의 digest를 고정한다. 파일 전송 실험은 공개 camt.053 XSD를
사용한 합성 데이터를 이용하며 은행의 실제 정산 업무 규격을 재현한 것은 아니다.

## 배포 검증

배포 게이트는 SMAUG1 + HAETAE2를 승인 정책으로 사용한다.

- 실제 TLS 협상 결과가 X25519 또는 ECDSA인 후보를 차단한다.
- Provider 로딩 실패와 필수 클라이언트의 접속 실패를 차단한다.
- 기존 서비스를 유지한 상태에서 정상 후보만 접속 경로에 반영한다.
- 새 인증서만 신뢰하는 연결 5회로 전환 결과를 확인한다.

`experiment.yml`은 push/PR에서 로컬 실험을 실행한다.
`aws-deploy.yml`은 main 브랜치에서 수동 실행하여 EC2 두 대에 **동일한 검증 이미지**를
배포하고 정상 승격·잘못된 후보 차단을 검증한다. 초기 AWS OIDC 역할 및 GitHub Secrets
설정이 필요하다. 원격 실행 완료 여부는 Actions 기록으로 확인해야 한다.

AWS 실험은 종료 시 컨테이너를 정리하고 EC2를 중지한다. 지속 운영 서비스가 아닌
일시적인 배포 PoC다. EBS는 유지된다. 라우터의 실험용 접속 선택 프리픽스를 사용하므로
범용 HTTPS 로드밸런서 구현은 아니다. 표본 연결 성공은 무중단 SLA의 증명이 아니다.

연구실 참고자료, 개인키, AWS 로그인 파일, 기존 실험의 원문 로그는 저장소에 포함하지 않는다.

## 실행 기록

- [GitHub CI 첫 성공 기록](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/35959675727): 파일 전환 및 PQC 배포 게이트 시험 통과.
- [GitHub → AWS 자동 배포 성공](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/35961683618): OIDC 인증, 동일 이미지 배포, 정상 후보 승격·오류 후보 차단, EC2 중지까지 통과.
- 해당 실행에서 로컬·AWS 각각 32개 판정 통과. AWS 활성 경로 표본 감시 86회 중 실패 0회. [보존한 결과 JSON](evidence/github-aws-35961683618.json)
- 검증 커밋: `55795e7afe40ca7c980de0209831dc16fee71dd3`. 잘못된 후보를 예상대로 차단한 시험은 성공으로 집계하며, 배포 승인과 구분한다.
- 첫 AWS 실행은 Docker 이미지 ID 비교에서 차단되고 자동 정리됐다. 저장 방식에 독립적인 이미지 config SHA-256 비교로 수정한 후 위 실행이 성공했다.

## AWS 실행 전 설정

GitHub OIDC 공급자와 이 저장소의 main 브랜치만 신뢰하는 IAM 역할이 필요하다.
역할은 서울의 실험용 인스턴스 두 대에 대한 시작·중지, 두 보안그룹의 인바운드 규칙 추가·제거,
인스턴스 상태 조회만 허용한다. 신규 EC2 생성이나 인스턴스 삭제 권한은 필요하지 않다.

Actions Secrets:

| 이름 | 내용 |
| --- | --- |
| `KPQC_AWS_ROLE_ARN` | OIDC로 사용할 역할 ARN |
| `KPQC_SERVER_INSTANCE_ID`, `KPQC_CLIENT_INSTANCE_ID` | 기존 실험용 EC2 ID |
| `KPQC_SERVER_SG_ID`, `KPQC_CLIENT_SG_ID` | 각 EC2에 연결된 보안그룹 ID |
| `KPQC_SSH_KEY` | 실험용 SSH 개인키 |
| `KPQC_KNOWN_HOSTS` | 별도로 검증한 호스트 키. 호스트 별칭은 `kpqc-server`, `kpqc-client` |

두 EC2에는 Docker가 설치되어 있어야 한다. 서버 TCP 4433은 클라이언트 보안그룹에서만
접속을 허용한다. 실행 시 GitHub runner의 IPv4 하나를 SSH 소스로 임시 허용하고 정리한다.
이미 실행 중인 인스턴스가 있으면 다른 작업과 충돌하지 않도록 시작 단계에서 중단한다.
강제 취소나 AWS API 장애로 정리가 실패할 수 있으므로 최종 `cleanup_complete`를 확인하고,
실패 시 EC2 상태와 임시 `kpqc-actions-*` SSH 규칙을 콘솔에서 확인한다.

이 공개 저장소에는 자체 호스팅 runner를 등록하지 않는다. AWS 워크플로는 PR에서 실행되지
않으며, GitHub 제공 runner에서 main 브랜치를 수동 실행한다.

- [GitHub 공식 AWS OIDC 설정](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
