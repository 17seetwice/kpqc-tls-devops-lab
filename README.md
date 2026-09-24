# KPQC TLS DevOps Lab

**한국어** | [English](README.en.md)

**새 버전 배포 시 PQC 암호 설정이 유지되는지 실제 TLS 연결로 검사하고, 정책을 위반한 후보의 배포를 차단하는 PoC입니다.**

국산 양자내성암호를 OpenSSL에 통합한 [`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3) 이미지를 사용합니다.
컨테이너·인증서·설정 변경으로 승인되지 않은 암호가 사용되거나 Provider 로딩이 실패하는 상황을 모사합니다.

## 동작 방식

![KPQC 배포 검증 아키텍처](docs/architecture/ko/fig1-architecture.png)

GitHub Actions가 이미지를 빌드·시험하고, SSH로 AWS EC2 두 대에 배포합니다.
클라이언트 EC2는 사설 IP로 서버의 후보 서비스에 TLS 연결을 시도합니다.
서버의 배포 게이트는 실제 협상 결과와 인증서 검증 결과를 정책에 대조합니다.

- **Active:** 현재 접속을 처리하는 기존 서비스.
- **Candidate:** 활성화 전에 검증하는 새 버전. 승인하면 active로 전환하고, 거절하면 제거하여 기존 서비스를 유지합니다.

기존 active도 PQC를 사용합니다. 이 배포 실험의 초점은 **갱신 과정에서 암호 설정이 이전 상태로 돌아가는 것을 방지하는 것**입니다.
TLS 연결에 성공하더라도 정책과 다른 암호를 사용하면 배포를 거절합니다.

[배포 흐름 그림](docs/architecture/ko/fig2-deployment-flow.png) · [English architecture](docs/architecture/en/fig1-architecture.png) · [English workflow](docs/architecture/en/fig2-deployment-flow.png)

## 배포 정책과 시험

현재 [정책](policies/pqc-required.json)은 **TLS 1.3 · SMAUG1 · HAETAE2 · TLS_AES_256_GCM_SHA384**를 요구합니다.
인증서 검증과 필수 PQC 클라이언트의 연결이 성공해야 하며, 기존 암호로 대체 연결하는 것은 허용하지 않습니다.

| 후보 구성 | 기대 동작 |
| --- | --- |
| SMAUG1 + HAETAE2 | 승인 후 활성 경로 전환 |
| X25519 + HAETAE2 | 키교환 정책 위반으로 차단 |
| SMAUG1 + ECDSA | 서명 정책 위반으로 차단 |
| Provider 로딩 실패 | 차단 |

각 후보를 독립적으로 판정합니다. 정상 후보의 전환 후에는 새 인증서만 신뢰하는 연결 5회로 전환을 확인합니다.
시험 증적에는 실제 협상 값, 검증 결과, 승인·거절 사유를 남깁니다.

## CI/CD 및 검증 결과

| 워크플로 | 실행 시점 | 역할 |
| --- | --- | --- |
| [CI](.github/workflows/experiment.yml) | push / PR | Docker 기반 파일 서명·전송 및 배포 게이트 시험 |
| [AWS 배포 검증](.github/workflows/aws-deploy.yml) | main에서 수동 실행 | 빌드·시험 → OIDC 인증 → EC2 배포 → 후보 판정·전환 → 증적 저장·정리 |

AWS 권한은 OIDC로 얻고, EC2 명령 실행에는 SSH를 사용합니다. CI 성공이 AWS 배포를 자동으로 시작하지는 않습니다.

[기록된 AWS 실행](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/35961683618)에서는 로컬·AWS 각각 **32개 검증 항목을 통과**했습니다.
AWS 활성 경로 표본 86회에서 실패는 0회였으며, 실행 후 EC2 중지와 임시 SSH 규칙 제거를 완료했습니다.
오류 후보를 예상대로 차단한 경우도 시험 통과에 포함합니다.
[결과 JSON](evidence/github-aws-35961683618.json)의 검증 커밋은 `55795e7`입니다.

## 실행과 코드 안내

Docker와 Docker Compose가 필요합니다. 기반 이미지는 `linux/amd64`이며 digest를 고정했습니다.

```sh
# 후보 승인·차단 및 활성 경로 전환 시험
docker compose -f compose.gate.yaml run --build --rm gate

# 합성 금융 XML의 파일 서명·TLS 전송 시험
docker compose run --build --rm lab
```

결과는 `artifacts/`에 저장됩니다. AWS 실행은 [사전 설정 가이드](docs/aws-setup.md)를 참고하세요.

| 파일 | 역할 |
| --- | --- |
| [gate_suite.py](scripts/gate_suite.py) | 후보별 시험 순서와 기대 결과 검증 |
| [gate_worker.py](scripts/gate_worker.py) | TLS 시험, 정책 판정, 경로 전환 |
| [ci_deploy.py](scripts/ci_deploy.py) | EC2 제어, 이미지 전달, 실험 종료 정리 |
| [tls_handshake.c](scripts/tls_handshake.c) | 핸드셰이크 측정과 협상 결과 수집 |
| [lab.py](scripts/lab.py) | 합성 파일 서명·전송 실험 |

## 실험 범위

전체 암호 실험은 SMAUG-T·NTRU+ KEM과 HAETAE·AIMer 서명을 대상으로 하며, 배포 게이트는 대표 조합 SMAUG1 + HAETAE2를 검증합니다.
합성 데이터는 공개 camt.053 XSD를 사용하며 실제 은행 정산 업무를 재현한 것은 아닙니다.

AWS 구성은 실험 후 EC2를 중지하는 일시적 PoC입니다(EBS는 유지).
TCP 라우터는 시험용 경로 선택 기능을 사용하며, 표본 연결 성공이 운영 환경의 무중단 SLA를 입증하지는 않습니다.
개인키·로그인 파일·고객 거래 데이터는 공개 저장소에 포함하지 않습니다.
