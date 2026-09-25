# KPQC TLS DevOps Lab

한국어 | [English](README.en.md)

국산 양자내성암호를 통합한 OpenSSL로 TLS 핸드셰이크 성능을 측정하고, 암호·성능 기준에 따라 배포를 승인하거나 거절하며, 장애 시 이전 승인 서비스로 복구하는 프로젝트입니다.

[`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3) 이미지를 사용합니다. 성능 측정 대상은 SMAUG·NTRU+ KEM (Key Encapsulation Mechanism)과 HAETAE·AIMer 서명입니다. 전환·복구 실험은 SMAUG1 + HAETAE2를 사용합니다.

## 기술 스택

### 암호 구현·성능 계측

![C](docs/assets/stack/c.svg) ![Python](docs/assets/stack/python.svg) ![OpenSSL](docs/assets/stack/openssl.svg)

C로 TLS 호출을 계측하고, Python으로 반복 실험·정책 판정·결과 검증을 수행합니다. KPQC가 통합된 OpenSSL이 실제 TLS 연결을 처리합니다.

### 실행 환경

![Docker](docs/assets/stack/docker.svg) ![Docker Compose](docs/assets/stack/compose.svg) ![Linux](docs/assets/stack/linux.svg) ![AWS EC2](docs/assets/stack/ec2.svg)

Docker·Compose로 로컬 실험을 실행하고, AWS EC2의 Linux 컨테이너에서 서버·클라이언트 실험을 수행합니다.

### CI/CD·클라우드 접근

![GitHub Actions](docs/assets/stack/actions.svg) ![AWS IAM](docs/assets/stack/iam.svg)

GitHub Actions가 빌드·시험·배포·정리를 실행합니다. AWS IAM (Identity and Access Management) 역할과 OIDC (OpenID Connect)로 단기 권한을 얻고, SSH (Secure Shell)로 원격 실행을 제어합니다.

### 분석·문서화

![Mermaid](docs/assets/stack/mermaid.svg) ![Matplotlib](docs/assets/stack/matplotlib.svg) ![Markdown](docs/assets/stack/markdown.svg)

Mermaid로 아키텍처를 작성하고 Matplotlib으로 결과 그래프를 생성합니다. 실험 방법과 결과는 Markdown·HTML로 제공합니다.

## 빠른 시작

처음에는 AWS 계정 없이 로컬 암호 정책 게이트부터 실행하세요. 서버와 클라이언트를 한 컨테이너에서 실행해 실제 TLS 연결을 만들고, 정상 후보 승인·잘못된 후보 거절을 시험합니다.

### 1. 사전 준비

Git, Python 3, Docker Engine 또는 실행 중인 Docker Desktop, Docker Compose가 필요합니다. Windows에서는 WSL2의 Linux 셸을 사용하세요. 아래 명령은 모두 저장소 루트에서 실행합니다.

```sh
git clone https://github.com/17seetwice/kpqc-tls-devops-lab.git
cd kpqc-tls-devops-lab

python3 --version
docker compose version
docker info
```

이 로컬 시험에는 `.env`, AWS 자격 증명, SSH 키가 필요하지 않습니다. Compose가 Linux amd64 이미지를 사용하도록 설정되어 있습니다. Apple Silicon 등 ARM 환경에서는 amd64 에뮬레이션이 필요하며, 해당 결과는 AWS 성능 수치와 직접 비교하지 않습니다.

### 2. 정책 검사와 실험 이미지 빌드

```sh
# Docker 없이 정책 판정과 정리 로직 검사
python3 scripts/test_gate_policy.py
python3 scripts/test_release_policy.py
python3 scripts/test_ci_deploy.py

# KPQC 기반 이미지 다운로드 및 TLS 시험 프로그램 빌드
docker compose -f compose.gate.yaml build
```

Python 시험은 모두 `OK`로 끝나야 합니다. 첫 이미지 빌드에는 인터넷 연결이 필요하며 다운로드·패키지 설치 시간이 걸립니다. 기반 이미지는 SHA-256 digest(이미지 내용을 식별하는 해시)로 고정되어 있습니다.

### 3. 로컬 TLS 배포 게이트 실행

```sh
mkdir -p artifacts
docker compose -f compose.gate.yaml run --rm gate
```

인증서 생성 → 기존 서비스 준비 → 고전·혼합 암호 후보 거절 → 정상 KPQC 후보 승인·경로 전환 → 결과 저장·정리 순서로 진행합니다. 잘못된 후보가 거절되는 로그는 예상한 시험 동작입니다. 종료 후 시험 컨테이너는 제거되고 결과 파일은 남습니다.

### 4. 결과 확인

결과는 `artifacts/local-gate-실행시각/results.json`에 저장됩니다. 다음 명령으로 가장 최근 실행의 상태와 검증 항목 수를 확인합니다.

```sh
python3 - <<'PYCODE'
import json
from pathlib import Path
runs = sorted(Path("artifacts").glob("local-gate-*/results.json"))
if not runs:
    raise SystemExit("No results.json found; check the experiment output.")
path = runs[-1]
result = json.loads(path.read_text())
checks = result["assertions"]
print("file:", path)
print("status:", result["status"])
print("checks:", sum(check["passed"] for check in checks), "/", len(checks))
print("cleanup_errors:", result.get("cleanup_errors", []))
PYCODE
```

현재 정상 종료 기준은 `status: passed`, `checks: 63 / 63`, `cleanup_errors: []`입니다.

### 5. 독립 TLS 성능 측정 실행하기

이 명령은 배포 게이트와 별개인 성능 벤치마크입니다. 게이트 시험 후 대표 3개 구성의 짧은 핸드셰이크 측정을 실행할 수 있습니다. 같은 이미지를 사용하며 새 프로세스·재사용 조건을 시험합니다.

```sh
docker compose -f compose.gate.yaml run --rm --entrypoint python3 gate /app/scripts/extended_handshake.py --local --balanced --smoke
```

결과는 `artifacts/local-extended-실행시각/results.json`에 저장됩니다. 전체 43개 구성·10블록을 실행하려면 `--smoke`를 제외하세요. 이 명령은 시간 측정용이며 별도 메모리 측정을 포함하지 않습니다. 로컬 시험은 loopback 통신이므로 두 EC2 사이의 네트워크 성능을 재현하지 않습니다.

### 6. AWS 실험으로 확장하기

[설정 가이드](docs/aws-setup.md)에 따라 실험용 EC2 두 대와 GitHub Actions Secrets를 준비한 뒤, Actions의 `AWS PQC deployment gates` → `Run workflow`에서 필요한 실험을 선택합니다.

- `balanced_latency`: 43개 구성의 새 프로세스·재사용 조건 비교.
- `systems_experiments`: MTU·네트워크 지연·HRR·동시 부하·부하 중 전환.
- `release_lifecycle`: 고전 암호에서 KPQC로 전환·성능 승인·장애 복구.

다른 계정으로 fork한 경우 [워크플로](.github/workflows/aws-deploy.yml)의 저장소 제한(`github.repository`)과 AWS 역할의 신뢰 조건을 본인 저장소에 맞춰야 합니다. 로컬 빠른 시작은 이 설정 없이 실행할 수 있습니다. AWS 실행 후에는 정리 기록의 `cleanup_complete`와 EC2 중지 상태를 확인하세요.

## 실험 구성

이 저장소는 서로 다른 두 가지 작업을 담습니다. 첫째는 KPQC TLS의 성능·네트워크 특성을 관측하는 실험입니다. 둘째는 관측 결과와 암호 정책을 배포 승인·복구에 사용하는 DevOps 실험입니다. TLS 성능·네트워크 벤치마크는 배포 파이프라인과 독립적으로 수행했습니다. 배포 승인은 별도의 후보 시험에서 고정 도착률 부하와 사전 설정한 SLO (Service Level Objective)를 적용합니다. 따라서 벤치마크 수치 자체가 배포 승인 입력은 아닙니다.

### TLS 성능·네트워크 특성 측정

이 항목은 TLS의 동작 시간과 자원·네트워크 영향을 측정하는 독립 벤치마크입니다.

- 42개 KPQC 조합과 고전 기준선의 지연·CPU·메시지 크기를 비교하고 별도 실행에서 메모리를 측정했습니다. 초기 실행은 지연 1,290회·메모리 129회, 후속 순서 비교 실행은 지연 2,580회를 분석했습니다. [측정 방법과 결과](experiments/performance/process-reuse/README.md)
- 대표 5개 조합에서 MTU·추가 지연·HRR·동시 접속 수에 따른 차이를 측정했습니다. 동시 부하 시험에서 273,091회 연결을 검증했습니다. [네트워크·처리량 결과](experiments/performance/network-and-load/README.md)

### 정책 기반 배포·복구 실험

이 항목은 실제 연결 검사와 성능 기준을 배포 결정에 연결하고, 자동화된 전환·복구 절차를 확인합니다.

- 암호 정책 후보 시험: 실제 협상에서 TLS 1.3·SMAUG1·HAETAE2가 선택되는지, 고전 암호 접속이나 TLS 1.2 접속을 허용하지 않는지 확인했습니다. 후보별 승인·거절 사유와 잘못된 증적을 거절하는지까지 63개 항목으로 검사했습니다. 실행별 상세 결과는 [`gate.public.json`](experiments/devops/gate-evidence/gate.public.json)에 있습니다.
- 성능 승인: 후보별 초당 10회씩 10초 × 3구간 동안 실패율·200ms 내 성공률·p95·부하 생성 지연을 검사했습니다. 정상 후보 두 개는 승인하고, 350ms 지연 주입 후보는 암호 검사를 통과했지만 성능 기준 위반으로 거절했습니다. 각 후보에서 TLS 연결 300회가 성공했습니다.
- 부하 중 전환·장애 복구: 전환 재시험에서 24,504회 중 실패 0회였습니다. 별도 프로세스 장애 시험에서는 2.951초 후 복구를 확인했으며, 장애 구간 150회 중 21회는 실패했습니다.
- 실행 자동화: GitHub Actions가 빌드·시험·AWS 실행·증적 저장·정리를 연결했습니다. 최종 실행에서 암호 정책 63개 및 전환·성능 승인·복구 24개 항목을 통과했고, EC2 중지와 임시 SSH 규칙 제거를 확인했습니다. [실행 기록](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36032662708)

실험별 수치는 실행 조건마다 따로 집계했으며 서로 다른 실행 결과를 합산하지 않습니다. 설계 배경과 상세 절차는 [전체 실험 설명](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.md)과 [HTML 자료](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.html)에 있습니다.

## 실험 환경과 측정 범위

서버와 클라이언트는 서울 동일 가용 영역의 m7i.large EC2 각각 한 대이며, 사설 IPv4로 통신합니다. 각 실험 컨테이너는 CPU 2개·메모리 512 MiB로 제한합니다. 동시 클라이언트 수는 EC2 대수가 아니라 클라이언트 인스턴스 안의 프로세스 수입니다.

| 실험 | 네트워크 조건 | 암호 구성 |
|---|---|---|
| TLS 성능: 프로세스 초기화·설정 재사용 조건 비교 | Docker host network, 인터페이스 MTU 9001 | SMAUG 1/3/5·NTRU+ 576/768/864/1152 × HAETAE 2/3/5·AIMer 128f/192f/256f 및 고전 기준선 |
| 네트워크·동시 부하 | Docker bridge, MTU 1500/9001 비교; 세부 조건은 개별 보고서 참조 | 고전 기준선 및 {SMAUG1, NTRU+ KEM768} × {HAETAE2, AIMer128f} |
| 성능 승인·장애 복구 | Docker bridge, MTU 1500 | 기존 X25519 + ECDSA P-256에서 SMAUG1 + HAETAE2로 전환 |

성능 비교는 여러 보안 파라미터를 포함하며 동일 보안 수준의 알고리즘 순위표가 아닙니다. 배포 실험은 이와 별도로 SMAUG1 + HAETAE2를 승인 조합으로 고정합니다. 다른 KPQC 조합을 배포하려면 정책도 변경해야 합니다.

| 지표 | 측정 구간과 의미 |
|---|---|
| TLS 핸드셰이크 지연 | 클라이언트 `SSL_connect` 호출 전후 단조 시계 차이. TCP 연결·명시적 초기화·시험용 준비 신호는 제외하며, 호출 내부의 지연 초기화는 포함될 수 있습니다. |
| 서버·클라이언트 CPU 시간 | 각 프로세스의 SSL 호출 전후 사용자·커널 CPU 시간 합의 차이. 네트워크 대기를 포함한 경과 시간과 구분합니다. |
| 핸드셰이크 구간 최대 RSS (Resident Set Size) 증가량 | 별도 실행에서 초기화 후 RSS 최고 기록을 재설정하고 호출 구간 증가량을 측정합니다. 구성별 3회이며 총 메모리 요구량이나 연결당 고정 비용을 뜻하지 않습니다. |
| 핸드셰이크 메시지 크기 | 메시지 콜백의 송수신 길이 합. TLS 레코드·TCP/IP 헤더와 재전송을 포함한 회선 전송량과 구분합니다. |

인증은 자체 서명 서버 인증서를 클라이언트에 사전 등록하고 이름을 검증하는 방식입니다. 서버 인증만 수행하며 mTLS (Mutual TLS)는 사용하지 않습니다. 시험용 준비 신호와 배포 경로 선택은 TLS 호출 밖에서 처리합니다. 해당 접속 절차와 커스텀 TLS 식별자는 동일 이미지의 시험 프로그램 간 사용을 전제로 합니다.

## TLS 성능 측정 결과

다음 결과는 배포 승인·복구 실험과 별도로 수행한 TLS 벤치마크에서 얻었습니다.

실행 순서를 균형화한 후속 측정은 43개 구성 × 2개 조건 × 30회로 총 2,580회를 분석했습니다. 준비·감시 연결은 분석에서 제외했습니다.

| 실행 조건 | X25519 + ECDSA P-256 중앙값 | KPQC 구성별 중앙값 범위 |
|---|---:|---:|
| 새 프로세스 | 1.724ms | 3.891–12.218ms |
| 프로세스 재사용 | 0.815ms | 2.852–11.500ms |

클라이언트의 `SSL_connect` 호출 구간을 측정한 값입니다. 범위는 42개 구성의 중앙값 중 최솟값과 최댓값입니다. 서버는 새 프로세스 조건에서 연결마다 자식 프로세스를 생성합니다. 재사용 조건에서도 연결과 TLS 핸드셰이크는 매번 새로 수행합니다. [측정 방법과 전체 결과](experiments/performance/process-reuse/README.md)

## 배포 흐름

![배포 및 복구 흐름](experiments/devops/deployment-recovery/architecture.ko.png)

1. 최초 KPQC 배포 후보: 기존 X25519 + ECDSA P-256 서비스를 SMAUG1 + HAETAE2로 전환합니다.
2. 후속 업데이트 후보: 동일 암호 조합을 유지하면서 새로운 서버 인증서와 별도 서버 프로세스로 갱신합니다. 업무 기능의 변경은 포함하지 않습니다.
3. 장애 복구: 후속 업데이트에 장애를 주입하고, 이전 승인 서비스의 현재 TLS 연결·인증서·암호 정책을 확인한 뒤 연결 경로를 복구합니다. 복구 후에도 KPQC를 유지합니다.

TLS 연결 성공과 배포 승인은 다릅니다. 실제 협상 결과가 승인된 암호 설정과 일치하고 성능 기준까지 만족해야 배포합니다. 정책 위반 또는 검증 자료 누락 시 기존 서비스를 유지합니다.

## 성능 기반 배포 승인 결과

서울 동일 가용 영역의 m7i.large EC2 (Elastic Compute Cloud) 두 대, 컨테이너별 CPU 2개·메모리 512 MiB, Docker 브리지 및 MTU (Maximum Transmission Unit) 1500 조건입니다. 후보마다 초당 10회, 10초 × 3구간으로 총 300회 접속을 시도했습니다.

SLO (Service Level Objective)는 시험 전에 고정한 모의 서비스 목표입니다. 모든 구간에서 실패율 ≤1%, 200ms 이내 성공 비율 ≥99%, 성공 접속 완료 시간 p95 ≤200ms를 요구합니다. 부하 생성 지연 p95는 50ms 이하여야 합니다.

| 배포 후보 | 암호 검사 | 구간별 접속 완료 시간 p95 | 배포 결과 |
|---|---|---|---|
| 350ms 지연 주입 후보 | 통과 | 382.56 / 382.46 / 381.96ms | 거절 |
| 최초 KPQC 배포 후보 | 통과 | 32.99 / 33.19 / 33.28ms | 승인 |
| 후속 업데이트 후보 | 통과 | 33.20 / 32.56 / 32.74ms | 승인 |

접속 완료 시간은 예정된 접속 시각부터 시험 클라이언트 종료까지이며 초기화·TCP·TLS 등을 포함합니다. 순수 TLS (Transport Layer Security) 핸드셰이크 시간은 `SSL_connect` 호출 구간으로 별도 기록합니다. p95는 관측값의 95%가 그 값 이하인 백분위수입니다.

장애 주입 요청부터 감지 1.596초, 복구 확인 2.951초를 관측했습니다. 장애 관측 중 150회 접속에서 21회 실패했고, 마지막 20회는 복구된 이전 서비스로 모두 성공했습니다. 이 결과는 무중단 전환을 의미하지 않습니다.

[한글 상세 보고서](experiments/devops/deployment-recovery/README.md) · [English report](experiments/devops/deployment-recovery/README.en.md) · [그림 모음](experiments/devops/deployment-recovery/gallery.html) · [원자료 검증](experiments/devops/deployment-recovery/audit.json)

## 암호 정책과 CI/CD

암호 정책은 TLS 1.3, SMAUG1, HAETAE2, TLS_AES_256_GCM_SHA384를 요구합니다. KEM과 서명은 cipher suite와 별도로 확인합니다. 고전 KEM·서명 허용, TLS 1.2, 인증서 검증 결과, 후보와 증적의 인증서 지문 불일치, 오래된 증적 및 프로브 오류를 검사합니다.

GitHub Actions는 이미지 빌드·로컬 시험 후 OIDC (OpenID Connect)로 AWS 단기 권한을 얻고, SSH (Secure Shell)로 기존 서버·클라이언트에 동일 이미지를 배포합니다. 실행 후 증적을 저장하고 두 EC2를 중지하며 임시 SSH 규칙을 제거합니다. push CI는 EC2를 시작하지 않습니다.

[이번 AWS 실행](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36032662708)에서 암호 정책 후보 시험 63개 항목과 전환·성능 승인·복구 시험 24개 항목이 기대한 결과를 냈습니다. 실험 소스는 `c232f7d`이며 후속 문서·CI 수정과 구분합니다. EC2 두 대의 중지는 워크플로와 별도 AWS 조회로 확인했습니다.

## 디렉터리 구성

성능·네트워크 측정과 DevOps 배포·복구 실험을 별도 디렉터리로 나눴습니다.

```text
kpqc-tls-devops-lab/
├── .github/workflows/       CI/CD 자동화
├── scripts/                 실험·계측·정책·배포 코드
├── policies/                암호 및 성능 승인 기준
├── experiments/
│   ├── performance/         TLS 성능·네트워크 측정
│   │   ├── initial/         초기 측정·원자료·그림
│   │   │   ├── data/        핸드셰이크 성능 원자료
│   │   │   └── figures/     성능 그래프
│   │   ├── process-reuse/   프로세스 조건 비교
│   │   └── network-and-load/ 네트워크·부하 시험
│   └── devops/              정책 기반 배포·복구
│       ├── gate-evidence/   후보별 암호 접속 검사·판정 결과(JSON)
│       └── deployment-recovery/ 전환·승인·장애 복구
├── docs/                    설정·실험 설명
├── Dockerfile.gate          KPQC 시험 이미지
└── compose.gate.yaml        로컬 게이트 설정
```

## 다른 실험 및 재현

| 실험 | 문서 |
|---|---|
| 43개 암호 구성의 핸드셰이크·CPU·메모리 측정 | [환경](experiments/performance/initial/01_environment.md) · [방법](experiments/performance/initial/02_methods.md) · [결과](experiments/performance/initial/03_results.md) |
| TLS 핸드셰이크 성능 측정: 프로세스 초기화와 설정 재사용 | [한국어](experiments/performance/process-reuse/README.md) · [English](experiments/performance/process-reuse/README.en.md) |
| MTU·네트워크 지연·HelloRetryRequest·동시 부하 측정 | [한국어](experiments/performance/network-and-load/README.md) · [English](experiments/performance/network-and-load/README.en.md) |
| 부하 중 배포 경로 전환 (DevOps 시나리오) | [실험 절과 결과](experiments/performance/network-and-load/README.md#4-부하-중-배포-전환) · [DevOps 실험 색인](experiments/devops/README.md) |
| 전환·성능 승인·자동 복구 | [계획](docs/RELEASE_EXPERIMENT_PLAN.md) · [한국어](experiments/devops/deployment-recovery/README.md) · [English](experiments/devops/deployment-recovery/README.en.md) |

각 실험은 환경과 측정 구간이 다르므로 개별 보고서의 조건과 실행 기록을 따릅니다. HTML 보고서와 그림 모음은 저장소를 내려받아 브라우저로 열 수 있습니다.

원자료부터 확인하려면 [초기 집계 CSV](experiments/performance/initial/data/summary.csv), [균형화 집계 CSV](experiments/performance/process-reuse/summary.csv), [암호 정책 후보 시험 결과](experiments/devops/gate-evidence/gate.public.json), [최종 배포 원자료](experiments/devops/deployment-recovery/measurements.public.json)를 참고하세요. `gate.public.json`에는 후보별 실제 TLS 접속 관측값, 승인·거절 판정과 사유, 증적 오류 검사 결과가 기록되어 있습니다. 그래프는 [초기 측정](experiments/performance/initial/gallery.html)·[균형화](experiments/performance/process-reuse/gallery.html)·[네트워크·부하](experiments/performance/network-and-load/gallery.html)·[배포·복구](experiments/devops/deployment-recovery/gallery.html)별로 제공합니다.

공개 배포 원자료의 판정과 수치를 AWS 실행 없이 다시 검증할 수 있습니다. 저장소 루트에서 실행하면 지정한 경로에 검증 요약이 생성됩니다.

```sh
python3 scripts/audit_release.py experiments/devops/deployment-recovery/measurements.public.json --out /tmp/kpqc-release-audit
```

핵심 코드: [TLS 계측](scripts/tls_handshake.c), [암호 정책](scripts/gate_policy.py), [성능 정책](scripts/release_policy.py), [전환·복구 실험](scripts/release_experiments.py), [AWS 실행·정리](scripts/ci_deploy.py). [AWS 설정 가이드](docs/aws-setup.md)

## 결과의 적용 범위

복구 대상 장애는 서버 프로세스 중단이며, 이전 승인 서비스는 같은 EC2에 유지됩니다. 시험용 TCP 라우터는 새 연결의 대상을 변경하며, 운영 로드밸런서의 연결 드레이닝이나 인스턴스·가용 영역 장애 복구를 검증한 것은 아닙니다.

최종 배포 실험의 개인키는 서버 컨테이너의 임시 메모리 파일시스템(`tmpfs`)에 보관하고 종료 시 컨테이너와 함께 제거합니다. 클라이언트에는 신뢰할 공개 인증서만 전달합니다. 별도 운영 키 관리 시스템은 구현하지 않았습니다.

반복 측정은 동일 인스턴스 쌍의 실행 안에서 수행했습니다. 여러 날짜·인스턴스 쌍의 독립 반복 검증은 포함하지 않습니다. 증적을 수집하고 판정하는 제어기는 신뢰하는 구성요소로 가정합니다.

결과는 사용자 제작 OpenSSL 이미지, 제한된 실험 부하 및 직접 신뢰한 서버 인증서 조건의 관측입니다. 운영 PKI (Public Key Infrastructure) 체인, 장기간 가용성, 실제 업무 처리의 연속성 및 다른 TLS 구현과의 상호운용은 검증 범위에 포함하지 않습니다. EC2 중지 후에도 EBS (Elastic Block Store) 볼륨은 유지됩니다.
