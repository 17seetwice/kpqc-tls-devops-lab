# kpqc-tls-devops-lab

KPQC TLS migration PoC with automated deployment gates and AWS EC2 validation.

국산 양자내성암호 OpenSSL 이미지로 TLS 협상과 전자서명 전환을 검증하는 실험이다.
SMAUG-T·NTRU+ KEM과 HAETAE·AIMer 서명을 대상으로 한다.

## 실행

```sh
docker compose run --build --rm lab
docker compose -f compose.gate.yaml run --build --rm gate
```

Docker amd64 이미지의 digest를 고정한다. 파일 전송 실험은 공개 camt.053 XSD를
사용한 합성 데이터를 이용하며 은행의 실제 정산 업무 규격을 재현한 것은 아니다.

## 배포 검증

배포 게이트는 SMAUG1 + HAETAE2를 승인 정책으로 사용한다.

- 실제 TLS 협상 결과가 X25519 또는 ECDSA인 후보를 차단한다.
- Provider 로딩 실패와 필수 클라이언트의 접속 실패를 차단한다.
- 기존 서비스를 유지한 상태에서 정상 후보만 접속 경로에 반영한다.
- 새 인증서만 신뢰하는 연결 5회로 전환 결과를 확인한다.

`experiment.yml`은 push/PR에서 로컬 실험을 실행한다.
`aws-deploy.yml`은 main 브랜치에서 수동 실행하여 EC2 두 대에 **동일한 검증 이미지**를
배포하고 정상 승격·잘못된 후보 차단을 검증한다. 초기 AWS OIDC 역할 및 GitHub Secrets
설정이 필요하다. 원격 실행 완료 여부는 Actions 기록으로 확인해야 한다.

AWS 실험은 종료 시 컨테이너를 정리하고 EC2를 중지한다. 지속 운영 서비스가 아닌
일시적인 배포 PoC다. EBS는 유지된다. 라우터의 실험용 접속 선택 프리픽스를 사용하므로
범용 HTTPS 로드밸런서 구현은 아니다. 표본 연결 성공은 무중단 SLA의 증명이 아니다.

연구실 참고자료, 개인키, AWS 로그인 파일, 기존 실험의 원문 로그는 저장소에 포함하지 않는다.
