# KPQC TLS 실험 자료

이 디렉터리는 성능 측정과 DevOps 배포 실험을 구분해 정리합니다. TLS 성능 벤치마크 결과는 배포 승인 입력으로 사용하지 않습니다. 배포 성능 판단은 별도 후보 시험에서 사전 설정 SLO (Service Level Objective)로 수행합니다.

## 성능·네트워크 측정

`performance/`에는 암호 구성별 핸드셰이크 지연·자원 사용·네트워크 조건·동시 부하 측정과 원자료가 있습니다.

- [초기 성능 측정 및 자료](performance/initial/README.md)
- [프로세스 초기화·설정 재사용 비교](performance/process-reuse/README.md) · [English](performance/process-reuse/README.en.md)
- [네트워크·동시 부하 측정](performance/network-and-load/README.md) · [English](performance/network-and-load/README.en.md)

## DevOps 배포·복구

`devops/`에는 암호 정책 게이트와 정책 기반 배포·장애 복구 시험이 있습니다.

- [암호 정책 게이트 공개 증적](devops/gate-evidence/gate.public.json)
- [전환·성능 승인·장애 복구](devops/deployment-recovery/README.md) · [English](devops/deployment-recovery/README.en.md)
- 네트워크 보고서의 [부하 중 배포 전환](performance/network-and-load/README.md#4-부하-중-배포-전환)은 성능 측정과 별도로 해석해야 하는 배포 시험 항목입니다.

## 공통 설계 문서

- [실행 환경과 용어](performance/initial/01_environment.md)
- [실험 과정과 분석 방법](performance/initial/02_methods.md)
- [초기 성능 결과와 캡션](performance/initial/03_results.md)
- [실험 아키텍처](04_architecture.md)
- [후속 실험 설계](05_future_experiments.md)
- [초기 그림 모음](performance/initial/gallery.html)
