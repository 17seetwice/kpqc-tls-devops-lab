# AWS 배포 실험 설정


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
