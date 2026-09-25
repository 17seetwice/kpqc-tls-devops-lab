# KPQC TLS DevOps Lab

**한국어** | [English](README.en.md)

국산 양자내성암호를 통합한 OpenSSL로 **TLS 핸드셰이크 성능을 측정하고, 암호·성능 기준에 따라 배포를 승인하거나 거절하며, 장애 시 이전 승인 서비스로 복구하는 프로젝트**입니다.

[`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3) 이미지를 사용합니다. 성능 측정 대상은 SMAUG·NTRU+ KEM (Key Encapsulation Mechanism)과 HAETAE·AIMer 서명입니다. 전환·복구 실험은 SMAUG1 + HAETAE2를 사용합니다.

## 검증 목표와 실험 구성

본 프로젝트의 검증 목표는 **제한된 자원에서 KPQC TLS의 실행 비용을 측정하고, 실제 연결에서 확인한 암호 설정과 응답 성능을 배포 승인·장애 복구에 적용할 수 있는지 확인하는 것**입니다. 성능 측정, 암호 정책 검사, 배포·복구를 다음과 같이 구분해 시험했습니다.

| 검증 대상 | 실험 방법과 판단 기준 | 확인한 결과 |
|---|---|---|
| **암호 구성별 핸드셰이크 비용** | SMAUG·NTRU+ 7개 파라미터와 HAETAE·AIMer 6개 파라미터의 42개 조합을 X25519 + ECDSA P-256과 비교했습니다. 전체 핸드셰이크 지연, 양쪽 프로세스의 CPU 시간, 메시지 바이트를 기록하고 메모리는 별도 실행에서 측정했습니다. | 초기 실행은 지연 1,290회·메모리 129회를 분석했습니다. 후속 실행에서는 새 프로세스·재사용 조건의 순서를 균형화해 2,580회를 분석했습니다. 구성별 지연은 아래 표에 제시합니다. |
| **네트워크·동시 접속의 영향** | 대표 5개 구성으로 MTU (Maximum Transmission Unit) 1500/9001, 추가 왕복 지연 0/10/30ms를 비교했습니다. HRR (HelloRetryRequest) 추가 왕복은 같은 최종 암호 조합끼리 비교하고, 서버 작업자 8개·클라이언트 프로세스 1/4/16개에서 처리량을 측정했습니다. | 추가 지연 30ms에서 SMAUG1 + AIMer128f의 지연은 MTU 1500에서 62.576ms, 9001에서 34.128ms였습니다. HRR은 약 31ms를 추가했습니다. 동시 부하에서는 총 273,091회 연결을 검증했습니다. |
| **금지된 암호 설정의 배포 차단** | 실제 협상 결과가 TLS 1.3·SMAUG1·HAETAE2·지정 cipher suite와 일치하고 인증서 검증을 통과해야 합니다. 고전 키 교환·서명 또는 TLS 1.2만 제시하는 클라이언트의 접속은 실패해야 합니다. 후보·인증서 지문·이미지·정책과 증적의 일치 및 신선도도 검사합니다. | KPQC와 고전 암호를 함께 허용하는 후보는 정상 KPQC 접속에 성공해도 거절했습니다. 증적 불일치·만료·프로브 오류를 포함해 암호 정책 검증 63개 항목을 통과했습니다. |
| **성능 기준에 따른 배포 승인** | 후보마다 초당 10회씩 10초 × 3구간을 시험했습니다. 각 구간에서 실패율 ≤1%, 200ms 내 성공률 ≥99%, 성공 접속 완료 시간 p95 ≤200ms, 부하 생성 지연 p95 ≤50ms를 요구했습니다. | 세 후보 모두 각각 TLS 연결 300회에 성공했습니다. 정상 두 후보는 승인했지만, 350ms 지연 주입 후보는 암호 검사를 통과해도 성능 기준 위반으로 거절했습니다. |
| **부하 중 전환과 장애 후 복구** | 정상 서비스 간 경로 전환과 신규 서비스 프로세스 중단을 별도로 시험했습니다. 장애 시 이전 승인 KPQC 서비스의 현재 TLS 상태와 인증서를 재확인하고 경로를 복구했습니다. | 부하 중 전환 재시험은 24,504회 접속에서 실패 0회였습니다. 별도 장애 주입 시험은 감지 1.596초·복구 2.951초였으며, 150회 중 실패 21회를 기록했습니다. |
| **배포 자동화와 추적 가능한 실행 기록** | GitHub Actions에서 이미지 빌드·시험, AWS 실행, 정책 판정, 증적 저장 및 자원 정리를 연결했습니다. 소스 커밋·이미지 식별자·인증서 지문·원자료를 남겼습니다. | 최종 AWS 실행에서 암호 정책 63개와 전환·성능 승인·복구 24개 검증 항목을 통과했습니다. 실행 후 두 EC2 중지와 임시 SSH 규칙 제거를 확인했습니다. |

예를 들어 정책이 **“SMAUG1만 허용”**인데 후보가 **“SMAUG1과 X25519 모두 허용”**으로 바뀌면, KPQC 연결 시험만으로는 변경을 놓칠 수 있습니다. 이 프로젝트는 X25519 전용 접속도 시험해 그 연결이 성공하면 후보를 거절합니다. 반대로 암호 설정이 모두 맞더라도 응답 성능 기준을 넘으면 배포하지 않습니다.

성능 비교에는 관측값을 사용하고, 배포 판단에는 사전에 정한 통과·거절 기준을 적용했습니다. 서로 다른 실행의 연결 수와 지연을 하나의 결과로 합산하지 않습니다. 네트워크 표의 지연은 세 블록 중앙값의 중앙값이며, 자세한 조건과 최초 전환 시험의 실패 기록은 [네트워크·부하 보고서](after_claude/systems/README.md)에 보존했습니다.

[실험 전체 설명: 목적·환경·방법·결과](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.md)에서 설계 이유와 단계별 결과를 확인할 수 있습니다. [HTML 자료](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.html)는 내려받아 브라우저로 열 수 있습니다.

## TLS 핸드셰이크 성능

실행 순서를 균형화한 후속 측정은 43개 구성 × 2개 조건 × 30회로 총 2,580회를 분석했습니다. 준비·감시 연결은 분석에서 제외했습니다.

| 실행 조건 | X25519 + ECDSA P-256 중앙값 | KPQC 구성별 중앙값 범위 |
|---|---:|---:|
| 새 프로세스 | 1.724ms | 3.891–12.218ms |
| 프로세스 재사용 | 0.815ms | 2.852–11.500ms |

클라이언트의 `SSL_connect` 호출 구간을 측정한 값입니다. 범위는 42개 구성의 중앙값 중 최솟값과 최댓값입니다. 서버는 새 프로세스 조건에서 연결마다 자식 프로세스를 생성합니다. 재사용 조건에서도 연결과 TLS 핸드셰이크는 매번 새로 수행합니다. [측정 방법과 전체 결과](after_claude/balanced/README.md)

## 배포 흐름

![배포 및 복구 흐름](after_claude/release/architecture.ko.png)

1. **최초 KPQC 배포 후보**: 기존 X25519 + ECDSA P-256 서비스를 SMAUG1 + HAETAE2로 전환합니다.
2. **후속 업데이트 후보**: 동일 암호 조합을 유지하면서 새로운 서버 인증서와 별도 서버 프로세스로 갱신합니다. 업무 기능의 변경은 포함하지 않습니다.
3. **장애 복구**: 후속 업데이트에 장애를 주입하고, 이전 승인 서비스의 현재 TLS 연결·인증서·암호 정책을 확인한 뒤 연결 경로를 복구합니다. 복구 후에도 KPQC를 유지합니다.

**TLS 연결 성공과 배포 승인은 다릅니다.** 실제 협상 결과가 승인된 암호 설정과 일치하고 성능 기준까지 만족해야 배포합니다. 정책 위반 또는 검증 자료 누락 시 기존 서비스를 유지합니다.

## 성능 기반 배포 승인 결과

서울 동일 가용 영역의 m7i.large EC2 (Elastic Compute Cloud) 두 대, 컨테이너별 CPU 2개·메모리 512 MiB, Docker 브리지 및 MTU (Maximum Transmission Unit) 1500 조건입니다. 후보마다 초당 10회, 10초 × 3구간으로 총 300회 접속을 시도했습니다.

SLO (Service Level Objective)는 시험 전에 고정한 모의 서비스 목표입니다. 모든 구간에서 실패율 ≤1%, 200ms 이내 성공 비율 ≥99%, 성공 접속 완료 시간 p95 ≤200ms를 요구합니다. 부하 생성 지연 p95는 50ms 이하여야 합니다.

| 배포 후보 | 암호 검사 | 구간별 접속 완료 시간 p95 | 배포 결과 |
|---|---|---|---|
| 350ms 지연 주입 후보 | 통과 | 382.56 / 382.46 / 381.96ms | 거절 |
| 최초 KPQC 배포 후보 | 통과 | 32.99 / 33.19 / 33.28ms | 승인 |
| 후속 업데이트 후보 | 통과 | 33.20 / 32.56 / 32.74ms | 승인 |

접속 완료 시간은 **예정된 접속 시각부터 시험 클라이언트 종료까지**이며 초기화·TCP·TLS 등을 포함합니다. 순수 TLS (Transport Layer Security) 핸드셰이크 시간은 `SSL_connect` 호출 구간으로 별도 기록합니다. p95는 관측값의 95%가 그 값 이하인 백분위수입니다.

장애 주입 요청부터 **감지 1.596초, 복구 확인 2.951초**를 관측했습니다. 장애 관측 중 150회 접속에서 21회 실패했고, 마지막 20회는 복구된 이전 서비스로 모두 성공했습니다. 이 결과는 무중단 전환을 의미하지 않습니다.

[한글 상세 보고서](after_claude/release/README.md) · [English report](after_claude/release/README.en.md) · [그림 모음](after_claude/release/gallery.html) · [원자료 검증](after_claude/release/audit.json)

## 암호 정책과 CI/CD

암호 정책은 TLS 1.3, SMAUG1, HAETAE2, TLS_AES_256_GCM_SHA384를 요구합니다. KEM과 서명은 cipher suite와 별도로 확인합니다. 고전 KEM·서명 허용, TLS 1.2, 인증서 검증 결과, 후보와 증적의 인증서 지문 불일치, 오래된 증적 및 프로브 오류를 검사합니다.

GitHub Actions는 이미지 빌드·로컬 시험 후 OIDC (OpenID Connect)로 AWS 단기 권한을 얻고, SSH (Secure Shell)로 기존 서버·클라이언트에 동일 이미지를 배포합니다. 실행 후 증적을 저장하고 두 EC2를 중지하며 임시 SSH 규칙을 제거합니다. push CI는 EC2를 시작하지 않습니다.

[이번 AWS 실행](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36032662708)에서 **기존 암호 정책 검증 63개, 전환·성능 승인·복구 검증 24개**를 통과했습니다. 실험 소스는 `c232f7d`이며 후속 문서·CI 수정과 구분합니다. EC2 두 대의 중지는 워크플로와 별도 AWS 조회로 확인했습니다.

## 다른 실험 및 재현

| 실험 | 문서 |
|---|---|
| 43개 암호 구성의 핸드셰이크·CPU·메모리 측정 | [환경](after_claude/01_environment.md) · [방법](after_claude/02_methods.md) · [결과](after_claude/03_results.md) |
| 새 프로세스·재사용 프로세스의 실행 순서 균형화 | [한국어](after_claude/balanced/README.md) · [English](after_claude/balanced/README.en.md) |
| MTU·네트워크 지연·HelloRetryRequest·동시 부하·부하 중 배포 | [한국어](after_claude/systems/README.md) · [English](after_claude/systems/README.en.md) |
| 전환·성능 승인·자동 복구 | [계획](docs/RELEASE_EXPERIMENT_PLAN.md) · [한국어](after_claude/release/README.md) · [English](after_claude/release/README.en.md) |

각 실험은 환경과 측정 구간이 다르므로 개별 보고서의 조건과 실행 기록을 따릅니다. HTML 보고서와 그림 모음은 저장소를 내려받아 브라우저로 열 수 있습니다.

Docker·Compose와 Linux amd64 실행 환경이 필요합니다. 기반 이미지는 SHA-256 digest로 고정했습니다.

```sh
python3 scripts/test_gate_policy.py
python3 scripts/test_release_policy.py
python3 scripts/test_ci_deploy.py
docker compose -f compose.gate.yaml run --build --rm gate
```

핵심 코드: [TLS 계측](scripts/tls_handshake.c), [암호 정책](scripts/gate_policy.py), [성능 정책](scripts/release_policy.py), [전환·복구 실험](scripts/release_experiments.py), [AWS 실행·정리](scripts/ci_deploy.py). [AWS 설정 가이드](docs/aws-setup.md)

복구 대상 장애는 서버 프로세스 중단이며, 이전 승인 서비스는 같은 EC2에 유지됩니다. 시험용 TCP 라우터는 새 연결의 대상을 변경하며, 운영 로드밸런서의 연결 드레이닝이나 인스턴스·가용 영역 장애 복구를 검증한 것은 아닙니다.

최종 배포 실험의 개인키는 서버 컨테이너의 임시 메모리 파일시스템(`tmpfs`)에 보관하고 종료 시 컨테이너와 함께 제거합니다. 클라이언트에는 신뢰할 공개 인증서만 전달합니다. 별도 운영 키 관리 시스템은 구현하지 않았습니다.

결과는 사용자 제작 OpenSSL 이미지, 제한된 실험 부하 및 직접 신뢰한 서버 인증서 조건의 관측입니다. 운영 PKI (Public Key Infrastructure) 체인, 장기간 가용성, 금융 거래 보존 및 다른 TLS 구현과의 상호운용은 검증 범위에 포함하지 않습니다. EC2 중지 후에도 EBS (Elastic Block Store) 볼륨은 유지됩니다.
