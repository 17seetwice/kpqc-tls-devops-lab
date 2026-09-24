# 측정 지표의 정의 및 해석 보완

2026-09-24 · 기존 기록 재검토 · 신규 실험 미실행

## 실행 환경

Docker는 라이브러리·실행 환경을 컨테이너로 실행하는 도구이며 Compose는 저장소의 YAML에 기록된 빌드·실행 설정을 적용한다. `linux/amd64`는 Linux의 x86-64 실행 형식으로 Intel 및 AMD 계열 CPU를 포함한다. ARM 호스트에서 에뮬레이션으로 기능을 실행할 수 있더라도 해당 성능을 EC2 (Elastic Compute Cloud) 네이티브 실행과 혼합하지 않는다.

기반 이미지 digest 고정은 태그 대신 `이름@sha256:...`로 이미지 내용을 지정하는 것이다. 기반 이미지 변경을 방지하지만 Dockerfile의 패키지 다운로드까지 모두 고정하는 것은 아니다. 실제 실행에서는 빌드한 이미지를 전달하고 이미지 식별자를 대조한다. [Docker 문서](https://docs.docker.com/reference/cli/docker/image/pull/)

MTU (Maximum Transmission Unit) 9001은 기존 AWS (Amazon Web Services) NIC에서 관측된 설정이다. 현재 실험 코드에는 MTU를 1500에서 9001로 변경하는 명령이 없다. Ethernet의 일반적인 IP MTU는 1500이며 EC2는 9001 jumbo MTU도 지원한다. NIC 설정만으로 전체 경로의 PMTU나 실제 패킷 크기를 검증한 것은 아니다. 후속 MTU 1500 비교는 아직 미실행이다. [AWS 문서](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-mtu.html)

## 시간 및 CPU

모노토닉 시계는 경과 시간 측정에 사용하는 뒤로 가지 않는 시계다. 현재 코드는 `CLOCK_MONOTONIC`의 SSL 호출 전후 차이를 사용한다. 달력 시각의 갑작스러운 변경 영향을 피하지만 모든 시계 주파수 보정으로부터 독립적인 것은 아니다. [Linux 문서](https://man7.org/linux/man-pages/man2/clock_gettime.2.html)

CPU (Central Processing Unit) 지표는 `getrusage(RUSAGE_SELF)`의 사용자·커널 누적 CPU 시간 합에서 호출 전후 차이를 계산한다. 네트워크 응답 대기 시간 전체가 CPU 시간에 들어가는 것은 아니다. 현재 연결별 프로세스/순차 처리 조건에서 적절한 프로세스 단위 지표다. CPU 계수 해상도와 계측 부가 비용이 있으며, 같은 프로세스의 여러 스레드가 동시에 연결을 처리하게 되면 이 값을 한 연결의 CPU 시간으로 해석할 수 없다. [getrusage 문서](https://man7.org/linux/man-pages/man2/getrusage.2.html)

## 메시지 바이트 및 프로토콜 조건

메시지 콜백은 OpenSSL이 프로토콜 메시지를 송수신할 때 등록한 관찰 함수를 호출하는 기능이다. 현재 코드는 핸드셰이크 메시지 유형만 골라 전달된 길이를 누적한다. TLS (Transport Layer Security) 핸드셰이크 헤더는 포함하지만 TLS 레코드·TCP/IP 헤더와 TCP (Transmission Control Protocol) 재전송 바이트는 포함하지 않는다. [OpenSSL 문서](https://docs.openssl.org/3.4/man3/SSL_CTX_set_msg_callback/)

세션 재개는 캐시·티켓을 비활성화하고 이전 세션을 새 SSL 객체에 공급하지 않는 설계로 제외하였다. Warm에서도 전체 핸드셰이크를 수행한다. HRR은 목표 그룹을 양 끝에 지정한 실행에서 관측되지 않았다. HRR (HelloRetryRequest) 유발 시험은 별도 수행해야 하며, HRR 0은 추가 왕복 경로를 시험했다는 뜻이 아니다. [RFC 8446](https://www.rfc-editor.org/rfc/rfc8446.html#section-4.1.4)

## RSS와 그래프 해석

RSS는 Resident Set Size, 즉 프로세스 주소 공간 중 현재 물리 메모리에 상주하는 부분의 크기다. 현재 값은 `VmHWM(호출 후) − VmHWM(재설정 후)`로 계산한 최고 RSS (Resident Set Size) 기록 증가량이다. 총 RSS·힙 할당량·서명 바이트와는 구분한다. 서버 인증서·키와 클라이언트 신뢰 자료의 초기 로딩은 기준점 이전에 수행한다. 이후에는 서버의 서명 생성, 클라이언트의 인증서 처리·서명 검증, 양쪽의 KEM (Key Encapsulation Mechanism)·버퍼·페이지 접근이 영향을 줄 수 있다.

PQC (Post-Quantum Cryptography) 42개 구성의 중앙값을 비교하면 서버가 더 큰 구성은 27개, 클라이언트가 더 큰 구성은 15개다. SMAUG1의 메모리 실행에서 다음 값이 기록되었다.

| 서명 | 클라이언트 RSS 증가 중앙값 (KiB) | 서버 RSS 증가 중앙값 (KiB) | 서버 송신 핸드셰이크 메시지 (bytes) |
|---|---:|---:|---:|
| HAETAE2 | 808 | 776 | 5,014 |
| HAETAE3 | 832 | 808 | 7,244 |
| HAETAE5 | 916 | 924 | 9,050 |
| AIMer128f | 648 | 728 | 12,877 |
| AIMer192f | 876 | 1,088 | 27,229 |
| AIMer256f | 920 | 1,100 | 51,374 |

각 행의 메모리 값은 3회 측정의 중앙값이다.

위 메시지 바이트는 서명 단독 크기가 아니라 서버가 보낸 핸드셰이크 메시지 합이다. 큰 메시지가 항상 큰 RSS 증가를 만드는 것은 아니다. 미리 확보한 페이지의 재사용, 작업 공간, 코드·스택 접근 등의 영향은 추가 계측 없이는 분리할 수 없다.

`clear_refs=5`의 최고 RSS 재설정 의미는 Linux 문서와 일치한다. 다만 `VmHWM`·`VmRSS`는 계수 정확도에 한계가 명시된 값이다. 현재 구현은 호출 전후 `/proc/self/status`를 읽고 계측용 스택·시스템 호출도 사용하므로 SSL 연산만을 완전히 격리한 메모리 값으로 주장하지 않는다. 일시적 메모리 사용이 기존 페이지를 재사용하면 RSS 증가는 나타나지 않을 수 있다. [clear_refs 문서](https://man7.org/linux/man-pages/man5/proc_pid_clear_refs.5.html) · [status 문서](https://man7.org/linux/man-pages/man5/proc_pid_status.5.html)

완료한 확인은 원자료–그래프 산술 일치, 재설정 성공, 양측 16 MiB 페이지 접근 양성 대조다. 빈 구간 반복 측정, 작은 크기별 페이지 접근 대조, 독립 계측 교차검증은 미실행이다. 따라서 현재 메모리 값은 탐색적 관측으로 유지하며 미세 차이의 순위나 서명 크기에 따른 인과 설명에 사용하지 않는다.
