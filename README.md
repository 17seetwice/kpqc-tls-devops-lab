# KPQC TLS DevOps Lab

**한국어** | [English](README.en.md)

**국산 양자내성암호의 TLS 핸드셰이크 비용을 측정하고, 새 버전이 승인된 암호 정책을 만족할 때만 활성 서비스로 전환하는 실험입니다.**

사용자가 KPQC를 OpenSSL에 통합한 [`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3) 이미지를 사용합니다. KEM은 SMAUG·NTRU+, 서명은 HAETAE·AIMer를 대상으로 합니다.

## 배포 검증

![정책 기반 배포 게이트](docs/architecture/ko/fig1-architecture.png)

- **Active**는 현재 트래픽을 처리하는 서비스, **candidate**는 활성화 전에 검사하는 새 버전입니다.
- 시험 클라이언트는 TCP 라우터의 후보 경로에 접속합니다. 게이트는 실제 협상·인증서 검증·금지된 접속의 거절을 정책과 비교합니다.
- 통과하면 후보로 활성 경로를 전환하고, 거절하면 기존 서비스를 유지합니다.

기존 active도 PQC를 사용합니다. 핵심은 업데이트 중 암호 설정이 이전 상태로 돌아가는 것을 탐지하는 것입니다. **TLS 접속 성공과 배포 승인은 다릅니다.** Provider 설치 여부는 암호 정책의 조건이 아닙니다.

현재 [정책](policies/pqc-required.json)은 TLS 1.3 · SMAUG1 · HAETAE2 · TLS_AES_256_GCM_SHA384를 요구합니다. KEM과 서명은 cipher suite와 별도로 확인합니다.

| 시험 | 기대 결과 |
|---|---|
| 승인된 PQC 구성 | 후보 승인·활성 경로 전환 |
| 잘못된 KEM 또는 서명 | 거절 |
| PQC와 고전암호를 함께 허용 | PQC 연결이 성공해도 고전 전용 접속이 성공하면 거절 |
| TLS 1.2 접속 | 거절; 별도 양성 대조로 프로브 기능 확인 |
| 후보·인증서·이미지·정책 불일치, 오래된 증적 | 거절 |
| 프로브 타임아웃·손상된 출력 | 거절 |

최종 로컬·AWS 게이트는 각각 **63/63개 검증 항목을 통과**했습니다. AWS 활성 경로 관측 69회에서 실패는 0회였습니다. 오류 후보의 예상된 거절도 시험 통과에 포함합니다. [최종 AWS 증적](after%20claude/data/gate.public.json)

## TLS 핸드셰이크 측정

서울 동일 AZ의 m7i.large EC2 두 대에서 사설 IPv4·Docker host network·MTU 9001로 측정했습니다. 7개 KEM 파라미터 × 6개 서명 파라미터와 고전 기준선, 총 43개 구성입니다.

| 조건 | X25519 + ECDSA | PQC 구성별 중앙값 범위 |
|---|---:|---:|
| 새 프로세스 | 1.388 ms | 3.503–11.287 ms |
| 프로세스 재사용 | 0.538 ms | 2.403–10.529 ms |
| 클라이언트 최대 RSS 증가 | 460 KiB | 648–980 KiB |
| 서버 최대 RSS 증가 | 420 KiB | 628–1,252 KiB |

시간은 클라이언트 `SSL_connect` 호출 구간만 측정합니다. 모드·구성별 5라운드 × 3회이며, 재사용 조건도 세션 재개 없는 전체 핸드셰이크입니다. 메모리는 별도 실행 3회의 호출 구간 최대 RSS 증가량입니다.

![기준선 및 SMAUG 핸드셰이크 지연](after%20claude/figures/ko/latency_smaug.png)

점은 구성별 15회 중앙값입니다. 전체 조합의 그림과 측정 조건은 [결과 및 캡션](after%20claude/03_results.md), [환경·용어](after%20claude/01_environment.md), [실험 방법](after%20claude/02_methods.md)에 있습니다. [영어 그림·캡션](after%20claude/captions.en.md)

## CI/CD와 실행 증적

![배포 워크플로](docs/architecture/ko/fig2-deployment-flow.png)

| 워크플로 | 실행 | 역할 |
|---|---|---|
| [CI](.github/workflows/experiment.yml) | push / PR | 정책·정리 회귀 시험, Docker 기반 파일 실험 및 게이트 통합 시험 |
| [AWS 배포 검증](.github/workflows/aws-deploy.yml) | main에서 수동 | 빌드·시험 → OIDC → SSH 배포 → 게이트 → 증적 저장·정리 |

OIDC는 AWS 단기 권한 취득에, SSH는 EC2 명령 실행에 사용합니다. push만으로 EC2를 시작하지 않습니다.

**최신 63항목 게이트 및 위 성능 수치는 로컬 제어기로 AWS에서 실행한 결과입니다.** 기존 [GitHub Actions 실행](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/35961683618)은 이전 32항목 시험이며 최신 결과와 구분합니다. 이번 공개 코드의 새 CI 결과는 저장소 Actions에서 확인할 수 있습니다.

## 실행 및 코드

Docker·Compose와 amd64 실행 환경이 필요합니다. 기반 이미지는 digest로 고정했습니다.

```sh
python3 scripts/test_gate_policy.py
python3 scripts/test_ci_deploy.py
docker compose -f compose.gate.yaml run --build --rm gate
```

| 파일 | 역할 |
|---|---|
| [gate_policy.py](scripts/gate_policy.py) | 관측된 TLS 결과의 정책 판정 |
| [gate_suite.py](scripts/gate_suite.py) / [gate_worker.py](scripts/gate_worker.py) | 후보·부정 프로브·전환 시험 |
| [tls_handshake.c](scripts/tls_handshake.c) | SSL 호출 시간·CPU·메모리·협상 계측 |
| [extended_handshake.py](scripts/extended_handshake.py) | 구성 순서 무작위화·반복 측정 |
| [ci_deploy.py](scripts/ci_deploy.py) | EC2 제어·이미지 동일성 확인·종료 정리 |
| [figures.py](after%20claude/scripts/figures.py) | 공개 원기록 재집계·한영 그림 생성 |

AWS 설정은 [가이드](docs/aws-setup.md)를 참조하세요. 기존 합성 금융 XML 서명·전송 실험은 `docker compose run --build --rm lab`으로 실행하며, 그 시간은 위 핸드셰이크 지표와 구분합니다.

## 범위와 후속 실험

단일 EC2 쌍·순차 연결·직접 신뢰한 서버 리프 인증서 조건입니다. 커스텀 식별자를 사용하므로 외부 TLS 구현과의 상호운용성은 입증하지 않습니다. 서로 다른 보안 파라미터의 성능 순위나 운영 환경의 무중단·처리량을 주장하지 않습니다. 후보 증적 검증은 신뢰한 제어기를 전제로 합니다.

현재 결과는 cold 이후 warm 순서입니다. [후속 계획](after%20claude/05_future_experiments.md)은 모드 순서 무작위화와 반복 실행, 네트워크 조건, 동시 부하, 부하 중 전환입니다. 계획은 완료 결과와 구분합니다. 실험 후 EC2는 중지하며 EBS는 유지합니다. 개인키·AWS 실행 설정·고객 데이터는 공개하지 않습니다.
