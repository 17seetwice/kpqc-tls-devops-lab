# DevOps 배포·복구 실험

이 묶음은 실제 TLS 협상 결과와 성능 기준을 배포 승인에 적용하고, 서비스 전환 및 장애 복구 절차를 시험합니다.

- [암호 정책 후보 시험 결과](gate-evidence/gate.public.json): 후보별 실제 TLS 접속 관측값, 승인·거절 판정과 사유, 증적 오류 시험 결과를 담은 실행 기록입니다. 암호 정책 파일 자체가 아니라 정책 적용 시험의 결과입니다.
- [전환·성능 승인·장애 복구](deployment-recovery/README.md) · [English](deployment-recovery/README.en.md).
- [부하 중 경로 전환](../performance/network-and-load/README.md#4-부하-중-배포-전환): 시스템 성능 보고서 안에 기록된 DevOps 시나리오.
