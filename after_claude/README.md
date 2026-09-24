# KPQC TLS: 실험 및 정책 기반 배포 검증

후속 실행 결과: [실행 순서 균형화 측정 보고서](balanced/README.md) · [English](balanced/README.en.md) · [그림 모음](balanced/gallery.html). 후속 결과는 기존 실행과 별도로 집계했으며 개별 실행 증적과 함께 제공한다.

국산 양자내성암호를 통합한 OpenSSL에서 TLS (Transport Layer Security) 1.3 핸드셰이크의 지연·자원 사용을 측정하고, 실제 협상 결과를 이용해 배포 후보의 정책 적합성을 검증한 실험 기록이다. 아래 주요 관측 표와 번호 문서는 최초 AWS (Amazon Web Services) 원자료의 재분석이다. 이후 실행은 `balanced/`와 `systems/`에 별도 소스·이미지·원기록으로 보존한다.

추가 네트워크·부하 실험: [한국어 보고서](systems/README.md) · [English](systems/README.en.md) · [그림 모음](systems/gallery.html). 첫 배포 부하 실패와 별도 재시험을 구분해 보존했다.

최신 전환·성능 승인·복구 실험: [한국어](release/README.md) · [English](release/README.en.md) · [그림 모음](release/gallery.html). 기존 결과와 별도로 집계했다.

## 문서

1. [실행 환경과 용어](01_environment.md)
2. [실험 과정과 분석 방법](02_methods.md)
3. [결과와 그림 캡션](03_results.md)
4. [실험 아키텍처](04_architecture.md)
5. [후속 실험 설계](05_future_experiments.md)

그림을 한 번에 보려면 [그림 모음](gallery.html)을 브라우저로 연다. 한국어·영어 PNG와 벡터 SVG를 `figures/ko`, `figures/en`에 제공한다. 그림은 같은 축 범위를 사용하며 모든 암호 조합을 포함한다. 영어 캡션은 [English captions](captions.en.md)에 있다.

## 주요 관측

| 측정 조건 | X25519 + ECDSA (Elliptic Curve Digital Signature Algorithm) | PQC (Post-Quantum Cryptography) 구성별 중앙값 범위 |
|---|---:|---:|
| 새 프로세스 핸드셰이크 | 1.388 ms | 3.503–11.287 ms |
| 프로세스 재사용 핸드셰이크 | 0.538 ms | 2.403–10.529 ms |
| 클라이언트 최대 RSS (Resident Set Size) 증가 | 460 KiB | 648–980 KiB |
| 서버 최대 RSS 증가 | 420 KiB | 628–1,252 KiB |

최종 AWS 배포 게이트는 63개 검증 항목을 통과했다. 표의 범위는 서로 다른 구성의 중앙값 범위이다. 서로 다른 보안 파라미터를 포함하므로 알고리즘 우열이나 동일 보안 수준의 순위를 의미하지 않는다.

## 재현과 증적

저장소 루트에서 `.venv/bin/python 'after_claude/scripts/figures.py'`를 실행하면 그림을 재생성한다. Python 환경에는 matplotlib이 필요하다. 스크립트는 세션 원기록에서 중앙값을 다시 계산하고 `summary.csv`의 129개 행과 대조한다.

- `data/measurements.public.json`: 성능·메모리 원기록의 비식별 사본
- `data/gate.public.json`: 최종 AWS 게이트 증적의 비식별 사본
- `data/summary.csv`, `summary.json`, `audit.json`: 기존 집계 및 점검 기록
- `data/SHA256SUMS`: 이 폴더에 복사한 데이터의 해시

실험 당시 소스·이미지 식별 정보는 원기록을 따른다. 성능 실험과 최종 게이트의 이미지는 구분한다. 이번 실행은 로컬 제어기로 수행했으며 GitHub Actions 실행으로 표기하지 않는다. 이 묶음은 GitHub 공개용으로 검토한 기존 실행 기록이다. 후속 실행 결과는 별도로 검토한다.
