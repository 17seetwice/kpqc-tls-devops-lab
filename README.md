# KPQC TLS DevOps Lab

한국어 | [English](README.en.md)

국산 양자내성암호를 통합한 OpenSSL로 TLS 핸드셰이크 성능을 측정하고, 암호·성능 기준에 따라 배포를 승인하거나 거절하며, 장애 시 이전 승인 서비스로 복구하는 프로젝트입니다.

[`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3) 이미지를 사용합니다. 성능 측정 대상은 SMAUG·NTRU+ KEM (Key Encapsulation Mechanism)과 HAETAE·AIMer 서명입니다. 전환·복구 실험은 SMAUG1 + HAETAE2를 사용합니다.

## 검증 목표와 실험 구성

본 프로젝트의 검증 목표는 제한된 자원에서 KPQC TLS의 실행 비용을 측정하고, 실제 연결에서 확인한 암호 설정과 응답 성능을 배포 승인·장애 복구에 적용할 수 있는지 확인하는 것입니다. 성능 측정, 암호 정책 검사, 배포·복구를 다음과 같이 구분해 시험했습니다.

### 1. 암호 구성별 핸드셰이크 비용

시험 방법과 판단 기준: SMAUG·NTRU+ 7개 파라미터와 HAETAE·AIMer 6개 파라미터의 42개 조합을 X25519 + ECDSA P-256과 비교했습니다. 전체 핸드셰이크 지연, 양쪽 프로세스의 CPU 시간, 메시지 바이트를 기록하고 메모리는 별도 실행에서 측정했습니다.

확인한 결과: 초기 실행은 지연 1,290회·메모리 129회를 분석했습니다. 후속 실행에서는 새 프로세스·재사용 조건의 순서를 균형화해 2,580회를 분석했습니다. 구성별 지연은 아래 표에 제시합니다.

### 2. 네트워크·동시 접속의 영향

시험 방법과 판단 기준: 대표 5개 구성으로 MTU (Maximum Transmission Unit) 1500/9001, 추가 왕복 지연 0/10/30ms를 비교했습니다. HRR (HelloRetryRequest) 추가 왕복은 같은 최종 암호 조합끼리 비교하고, 서버 작업자 8개·클라이언트 프로세스 1/4/16개에서 처리량을 측정했습니다.

확인한 결과: 추가 지연 30ms에서 SMAUG1 + AIMer128f의 지연은 MTU 1500에서 62.576ms, 9001에서 34.128ms였습니다. HRR은 약 31ms를 추가했습니다. 동시 부하에서는 총 273,091회 연결을 검증했습니다.

### 3. 금지된 암호 설정의 배포 차단

시험 방법과 판단 기준: 실제 협상 결과가 TLS 1.3·SMAUG1·HAETAE2·지정 cipher suite와 일치하고 인증서 검증을 통과해야 합니다. 고전 키 교환·서명 또는 TLS 1.2만 제시하는 클라이언트의 접속은 실패해야 합니다. 후보·인증서 지문·이미지·정책과 증적의 일치 및 신선도도 검사합니다.

확인한 결과: KPQC와 고전 암호를 함께 허용하는 후보는 정상 KPQC 접속에 성공해도 거절했습니다. 증적 불일치·만료·프로브 오류를 포함해 암호 정책 검증 63개 항목을 통과했습니다.

### 4. 성능 기준에 따른 배포 승인

시험 방법과 판단 기준: 후보마다 초당 10회씩 10초 × 3구간을 시험했습니다. 각 구간에서 실패율 ≤1%, 200ms 내 성공률 ≥99%, 성공 접속 완료 시간 p95 ≤200ms, 부하 생성 지연 p95 ≤50ms를 요구했습니다.

확인한 결과: 세 후보 모두 각각 TLS 연결 300회에 성공했습니다. 정상 두 후보는 승인했지만, 350ms 지연 주입 후보는 암호 검사를 통과해도 성능 기준 위반으로 거절했습니다.

### 5. 부하 중 전환과 장애 후 복구

시험 방법과 판단 기준: 정상 서비스 간 경로 전환과 신규 서비스 프로세스 중단을 별도로 시험했습니다. 장애 시 이전 승인 KPQC 서비스의 현재 TLS 상태와 인증서를 재확인하고 경로를 복구했습니다.

확인한 결과: 부하 중 전환 재시험은 24,504회 접속에서 실패 0회였습니다. 별도 장애 주입 시험은 감지 1.596초·복구 2.951초였으며, 150회 중 실패 21회를 기록했습니다.

### 6. 배포 자동화와 추적 가능한 실행 기록

시험 방법과 판단 기준: GitHub Actions에서 이미지 빌드·시험, AWS 실행, 정책 판정, 증적 저장 및 자원 정리를 연결했습니다. 소스 커밋·이미지 식별자·인증서 지문·원자료를 남겼습니다.

확인한 결과: 최종 AWS 실행에서 암호 정책 63개와 전환·성능 승인·복구 24개 검증 항목을 통과했습니다. 실행 후 두 EC2 중지와 임시 SSH 규칙 제거를 확인했습니다.

예를 들어 정책이 “SMAUG1만 허용”인데 후보가 “SMAUG1과 X25519 모두 허용”으로 바뀌면, KPQC 연결 시험만으로는 변경을 놓칠 수 있습니다. 이 프로젝트는 X25519 전용 접속도 시험해 그 연결이 성공하면 후보를 거절합니다. 반대로 암호 설정이 모두 맞더라도 응답 성능 기준을 넘으면 배포하지 않습니다.

성능 비교에는 관측값을 사용하고, 배포 판단에는 사전에 정한 통과·거절 기준을 적용했습니다. 서로 다른 실행의 연결 수와 지연을 하나의 결과로 합산하지 않습니다. 네트워크 표의 지연은 세 블록 중앙값의 중앙값이며, 자세한 조건과 최초 전환 시험의 실패 기록은 [네트워크·부하 보고서](after_claude/systems/README.md)에 보존했습니다.

[실험 전체 설명: 목적·환경·방법·결과](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.md)에서 설계 이유와 단계별 결과를 확인할 수 있습니다. [HTML 자료](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.html)는 내려받아 브라우저로 열 수 있습니다.

## 실험 환경과 측정 범위

서버와 클라이언트는 서울 동일 가용 영역의 m7i.large EC2 각각 한 대이며, 사설 IPv4로 통신합니다. 각 실험 컨테이너는 CPU 2개·메모리 512 MiB로 제한합니다. 동시 클라이언트 수는 EC2 대수가 아니라 클라이언트 인스턴스 안의 프로세스 수입니다.

| 실험 | 네트워크 조건 | 암호 구성 |
|---|---|---|
| 초기·실행 순서 균형화 측정 | Docker host network, 인터페이스 MTU 9001 | SMAUG 1/3/5·NTRU+ 576/768/864/1152 × HAETAE 2/3/5·AIMer 128f/192f/256f 및 고전 기준선 |
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

## TLS 핸드셰이크 성능

실행 순서를 균형화한 후속 측정은 43개 구성 × 2개 조건 × 30회로 총 2,580회를 분석했습니다. 준비·감시 연결은 분석에서 제외했습니다.

| 실행 조건 | X25519 + ECDSA P-256 중앙값 | KPQC 구성별 중앙값 범위 |
|---|---:|---:|
| 새 프로세스 | 1.724ms | 3.891–12.218ms |
| 프로세스 재사용 | 0.815ms | 2.852–11.500ms |

클라이언트의 `SSL_connect` 호출 구간을 측정한 값입니다. 범위는 42개 구성의 중앙값 중 최솟값과 최댓값입니다. 서버는 새 프로세스 조건에서 연결마다 자식 프로세스를 생성합니다. 재사용 조건에서도 연결과 TLS 핸드셰이크는 매번 새로 수행합니다. [측정 방법과 전체 결과](after_claude/balanced/README.md)

## 배포 흐름

![배포 및 복구 흐름](after_claude/release/architecture.ko.png)

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

[한글 상세 보고서](after_claude/release/README.md) · [English report](after_claude/release/README.en.md) · [그림 모음](after_claude/release/gallery.html) · [원자료 검증](after_claude/release/audit.json)

## 암호 정책과 CI/CD

암호 정책은 TLS 1.3, SMAUG1, HAETAE2, TLS_AES_256_GCM_SHA384를 요구합니다. KEM과 서명은 cipher suite와 별도로 확인합니다. 고전 KEM·서명 허용, TLS 1.2, 인증서 검증 결과, 후보와 증적의 인증서 지문 불일치, 오래된 증적 및 프로브 오류를 검사합니다.

GitHub Actions는 이미지 빌드·로컬 시험 후 OIDC (OpenID Connect)로 AWS 단기 권한을 얻고, SSH (Secure Shell)로 기존 서버·클라이언트에 동일 이미지를 배포합니다. 실행 후 증적을 저장하고 두 EC2를 중지하며 임시 SSH 규칙을 제거합니다. push CI는 EC2를 시작하지 않습니다.

[이번 AWS 실행](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36032662708)에서 기존 암호 정책 검증 63개, 전환·성능 승인·복구 검증 24개를 통과했습니다. 실험 소스는 `c232f7d`이며 후속 문서·CI 수정과 구분합니다. EC2 두 대의 중지는 워크플로와 별도 AWS 조회로 확인했습니다.

## 다른 실험 및 재현

| 실험 | 문서 |
|---|---|
| 43개 암호 구성의 핸드셰이크·CPU·메모리 측정 | [환경](after_claude/01_environment.md) · [방법](after_claude/02_methods.md) · [결과](after_claude/03_results.md) |
| 새 프로세스·재사용 프로세스의 실행 순서 균형화 | [한국어](after_claude/balanced/README.md) · [English](after_claude/balanced/README.en.md) |
| MTU·네트워크 지연·HelloRetryRequest·동시 부하·부하 중 배포 | [한국어](after_claude/systems/README.md) · [English](after_claude/systems/README.en.md) |
| 전환·성능 승인·자동 복구 | [계획](docs/RELEASE_EXPERIMENT_PLAN.md) · [한국어](after_claude/release/README.md) · [English](after_claude/release/README.en.md) |

각 실험은 환경과 측정 구간이 다르므로 개별 보고서의 조건과 실행 기록을 따릅니다. HTML 보고서와 그림 모음은 저장소를 내려받아 브라우저로 열 수 있습니다.

원자료부터 확인하려면 [초기 집계 CSV](after_claude/data/summary.csv), [균형화 집계 CSV](after_claude/balanced/summary.csv), [암호 정책 시험 기록](after_claude/data/gate.public.json), [최종 배포 원자료](after_claude/release/measurements.public.json)를 참고하세요. 그래프는 [초기 측정](after_claude/gallery.html)·[균형화](after_claude/balanced/gallery.html)·[네트워크·부하](after_claude/systems/gallery.html)·[배포·복구](after_claude/release/gallery.html)별로 제공합니다.

공개 배포 원자료의 판정과 수치를 AWS 실행 없이 다시 검증할 수 있습니다. 저장소 루트에서 실행하면 지정한 경로에 검증 요약이 생성됩니다.

```sh
python3 scripts/audit_release.py after_claude/release/measurements.public.json --out /tmp/kpqc-release-audit
```

아래 명령은 정책 함수 시험과 로컬 Docker 통합 시험입니다. Docker·Compose와 Linux amd64(x86-64) 실행 환경이 필요합니다. 기반 이미지는 SHA-256 digest, 즉 이미지 내용을 식별하는 해시로 고정해 같은 이름의 다른 이미지로 바뀌는 것을 방지합니다.

```sh
python3 scripts/test_gate_policy.py
python3 scripts/test_release_policy.py
python3 scripts/test_ci_deploy.py
docker compose -f compose.gate.yaml run --build --rm gate
```

AWS 측정은 [설정 가이드](docs/aws-setup.md)를 따른 뒤 [수동 워크플로](.github/workflows/aws-deploy.yml)에서 실행합니다. `balanced_latency`는 실행 순서 균형화, `systems_experiments`는 네트워크·동시 부하, `release_lifecycle`은 전환·성능 승인·복구를 선택합니다. 로컬 통합 시험은 loopback 통신이며 AWS 두 인스턴스의 성능 결과를 재현하는 명령은 아닙니다.

핵심 코드: [TLS 계측](scripts/tls_handshake.c), [암호 정책](scripts/gate_policy.py), [성능 정책](scripts/release_policy.py), [전환·복구 실험](scripts/release_experiments.py), [AWS 실행·정리](scripts/ci_deploy.py). [AWS 설정 가이드](docs/aws-setup.md)

## 결과의 적용 범위

복구 대상 장애는 서버 프로세스 중단이며, 이전 승인 서비스는 같은 EC2에 유지됩니다. 시험용 TCP 라우터는 새 연결의 대상을 변경하며, 운영 로드밸런서의 연결 드레이닝이나 인스턴스·가용 영역 장애 복구를 검증한 것은 아닙니다.

최종 배포 실험의 개인키는 서버 컨테이너의 임시 메모리 파일시스템(`tmpfs`)에 보관하고 종료 시 컨테이너와 함께 제거합니다. 클라이언트에는 신뢰할 공개 인증서만 전달합니다. 별도 운영 키 관리 시스템은 구현하지 않았습니다.

반복 측정은 동일 인스턴스 쌍의 실행 안에서 수행했습니다. 여러 날짜·인스턴스 쌍의 독립 반복 검증은 포함하지 않습니다. 증적을 수집하고 판정하는 제어기는 신뢰하는 구성요소로 가정합니다.

결과는 사용자 제작 OpenSSL 이미지, 제한된 실험 부하 및 직접 신뢰한 서버 인증서 조건의 관측입니다. 운영 PKI (Public Key Infrastructure) 체인, 장기간 가용성, 금융 거래 보존 및 다른 TLS 구현과의 상호운용은 검증 범위에 포함하지 않습니다. EC2 중지 후에도 EBS (Elastic Block Store) 볼륨은 유지됩니다.
