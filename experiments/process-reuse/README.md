# 프로세스 재사용 여부에 따른 TLS 핸드셰이크 지연 비교

한국어 | [English](README.en.md)

실행: `aws-extended-20260924T134811Z` · 소스: `cfd6bcc` · [GitHub Actions 증적](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36007402798)

## 무엇을 비교한 실험인가?

같은 암호 조합이라도 연결할 때마다 시험 프로그램을 새로 실행하는 경우와, 이미 실행 중인 프로그램에서 새 연결을 만드는 경우의 TLS 핸드셰이크 시간이 다른지 비교했다.

### 이 실험에서 프로세스 재사용이란?

프로세스 재사용은 실행 중인 TLS 시험 프로그램과 준비된 TLS 설정을 다음 연결에도 사용하는 것이다.

- 새 프로세스 조건(cold): 연결마다 클라이언트를 새로 실행하고, 서버도 새 자식 프로세스에서 TLS 설정을 준비한다.
- 재사용 조건(warm): 같은 프로그램의 실행 상태와 TLS 설정을 유지하면서 연결을 반복한다. 한 암호 구성에서 준비 연결 2회 후 3회를 분석한다.

두 조건 모두 연결은 매번 새로 만들고, 인증과 키 교환을 포함한 전체 TLS 핸드셰이크를 수행한다. 이전 연결의 상태로 절차를 줄이는 TLS 세션 재개는 사용하지 않는다. 이 실험은 프로그램과 설정의 재사용 여부에 따라 핸드셰이크 지연이 달라지는지 비교한다.

재사용은 한 암호 구성의 반복 연결에 적용한다. 새 프로세스 조건에서도 운영체제 캐시를 강제로 비우지는 않는다.

### 측정 순서를 바꾼 이유

새 프로세스 조건을 항상 먼저 측정하면, 재사용 조건은 항상 시간이 지난 뒤 측정된다. 그 사이 CPU 부하나 캐시 상태가 달라질 수 있어, 관측한 차이에 프로세스 재사용뿐 아니라 실행 시점의 영향도 섞일 수 있다.

이를 줄이기 위해 두 조건을 한 번씩 측정하는 묶음을 ‘블록’으로 정하고 총 10개를 실행했다.

- 5개 블록: 새 프로세스 조건 → 프로세스 재사용 조건.
- 나머지 5개 블록: 프로세스 재사용 조건 → 새 프로세스 조건.
- 이 10개 블록의 순서도 섞었다. 블록 안에서는 43개 암호 구성의 순서를 무작위로 정하되, 두 조건에 같은 구성 순서를 적용했다.

이처럼 어느 조건이 먼저 실행되는지 횟수를 맞춘 절차를 ‘실행 순서 균형화’라고 부른다. 비교하려는 대상은 프로세스 재사용 여부이고, 순서 균형화는 특정 조건이 늘 먼저 또는 나중에 측정되는 편향을 줄이기 위한 방법이다.

### 시간은 어디부터 어디까지 재는가?

프로세스 생성·명시적인 TLS 설정 준비·TCP 연결·시험용 준비 신호는 측정 전에 끝낸다. 대표 지표는 클라이언트 `SSL_connect` 호출 직전부터 반환 직후까지의 경과 시간이다. 따라서 프로그램 시작 전체 비용을 비교한 결과는 아니다. 다만 호출 안에서 처음 수행되는 초기화나 캐시 상태의 영향은 측정 시간에 포함될 수 있다.

## 방법 및 검증

기존 EC2 (Elastic Compute Cloud) 두 대에서 TLS (Transport Layer Security) 연결을 순차 측정하였다. 새 인스턴스를 생성하지 않았다. 10개 블록에서 cold-first와 warm-first를 각각 5개로 배정하고 순서를 섞었다. 블록 내 구성 순서는 무작위화하고 두 모드 사이에 같은 순서를 사용했다. 전체 43개 구성·모드별 분석 표본은 30개다.

총 3,600회 수집, 2,580회 분석, 준비·감시 연결 1,020회다. 원기록의 실제 그룹·서명 식별자, 인증서 검증, TLS 버전·cipher, 세션 재개 없음, HRR (HelloRetryRequest) 0, 방향별 메시지 바이트 대응을 확인했다. 5:5 시작 순서와 짝지은 구성 순서도 검증했다. 이번 실행에서는 메모리를 측정하지 않았다.

### 원기록의 어떤 필드를 검사했는가?

아래 이름은 설명을 위한 별칭이 아니라 JSON 원기록의 실제 필드명이다. 한 연결의 기록은 `rounds[].profiles[].sessions[]` 아래 `client`와 `server`에 각각 저장된다. `kem`·`signature`는 시험하려는 구성 이름이고, `group_code`·`signature_code`는 TLS 메시지에서 관측한 숫자 식별자다.

| 검증 항목 | JSON 필드 | 기대값 또는 비교 방법 |
|---|---|---|
| 핸드셰이크 성공 | `success` | `true` |
| 키 교환 그룹 | `group_code` | `codes[k]`와 일치. 예: `smaug1` → `65056` (`0xFE20`) |
| 서버 인증 서명 | `signature_code` | `sigs[s]`와 일치. 예: `haetae2` → `65408` (`0xFF80`) |
| 인증서 검증 | `verify_result` | `0`: 검증 오류 없음 |
| TLS 버전 | `tls_version` | `"TLSv1.3"` |
| Cipher suite | `cipher` | `"TLS_AES_256_GCM_SHA384"` |
| TLS 세션 재개 | `reused` | `false`: 세션 재개를 사용하지 않음 |
| 추가 왕복 HRR | `hello_retry_requests` | `0`: HRR이 발생하지 않음 |
| 방향별 메시지 크기 | `sent_handshake_bytes`, `received_handshake_bytes` | 클라이언트 송신 = 서버 수신, 서버 송신 = 클라이언트 수신 |

`reused`는 프로세스 재사용 여부가 아니라 TLS 세션 재개 여부다. 프로세스 재사용 조건은 `rounds[].mode == "warm"`으로 구분한다. 인증서 검증의 의미는 클라이언트가 서버 인증서를 검증했다는 것이며, 서버 기록의 `verify_result == 0`을 클라이언트 인증 성공으로 해석하지 않는다. 이 실험은 서버 인증만 수행한다.

그룹·서명 번호는 이 실험 이미지의 매핑이다. 예를 들어 HAETAE2라는 이름이 JSON에 직접 들어가는 필드와 실제 관측 번호를 비교하는 필드는 다음처럼 구분된다.

```text
시험 구성: profiles[].kem = "smaug1", profiles[].signature = "haetae2"
관측 결과: sessions[].client.group_code = 65056
           sessions[].client.signature_code = 65408
```

전체 이름→번호 매핑은 [scripts/extended_handshake.py:39–40](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/scripts/extended_handshake.py#L39-L40)에 있다.

```python
    codes={'X25519':29,'smaug1':65056,'smaug3':65059,'smaug5':65062,'ntruplus_kem576':65064,'ntruplus_kem768':65067,'ntruplus_kem864':65070,'ntruplus_kem1152':65073}
    sigs={'EC':1027,'haetae2':65408,'haetae3':65409,'haetae5':65410,'aimer128f':65411,'aimer192f':65413,'aimer256f':65415}
```

C 프로그램에서 `CertificateVerify`의 서명 번호는 [scripts/tls_handshake.c:43–47](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/scripts/tls_handshake.c#L43-L47), `ServerHello`의 `key_share` 그룹 번호는 [scripts/tls_handshake.c:70–76](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/scripts/tls_handshake.c#L70-L76)에서 읽는다. 이 값들을 JSON 필드로 출력하는 부분은 [scripts/tls_handshake.c:196–209](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/scripts/tls_handshake.c#L196-L209)이다.

수집 즉시 검사하는 코드는 [scripts/extended_handshake.py:70–75](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/scripts/extended_handshake.py#L70-L75)이다. `c`는 클라이언트 기록, `t`는 서버 기록이며, `r`은 양쪽을 차례로 가리킨다. `k`·`s`는 현재 시험의 KEM·서명 이름이다.

```python
            for i,(c,t) in enumerate(zip(cs,ss)):
                for r in [c,t]:
                    assert r['success'] and r['group_code']==codes[k] and r['signature_code']==sigs[s] and not r['reused'] and r['verify_result']==0
                    assert r['tls_version']=='TLSv1.3' and r['cipher']=='TLS_AES_256_GCM_SHA384' and r['hello_retry_requests']==0
                    if mode=='memory':assert r['rss_peak_reset_ok'] and r['rss_window_peak_growth_kib']>=0
                assert c['sent_handshake_bytes']==t['received_handshake_bytes'] and t['sent_handshake_bytes']==c['received_handshake_bytes']
```

`mode == 'memory'` 검사는 공용 수집기의 별도 메모리 실행용이다. 이 균형화 실행의 `mode`는 `cold` 또는 `warm`이므로 해당 분기는 실행되지 않았다.

공개 원기록의 SMAUG1 + HAETAE2 첫 표본에서는 클라이언트 송신 `876`바이트 = 서버 수신 `876`바이트, 서버 송신 `5014`바이트 = 클라이언트 수신 `5014`바이트였다. 이는 해당 표본의 TLS 핸드셰이크 메시지 길이이며 TCP/IP 헤더·재전송을 포함한 회선 전송량이 아니다.

### 5:5 시작 순서는 코드에서 어떻게 만드는가?

실행 계획 생성: [scripts/extended_handshake.py:44–52](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/scripts/extended_handshake.py#L44-L52).

```python
    rng=random.Random(D['random_seed'])
    schedule=[]
    if args.balanced:
        first_modes=['cold']*5+['warm']*5
        rng.shuffle(first_modes)
        for block,first in enumerate(first_modes[:1] if args.smoke else first_modes):
            order=list(pairs);rng.shuffle(order)
            for mode in [first,'warm' if first=='cold' else 'cold']:
                schedule.append((mode,block,list(order)))
```

- `first_modes`: `cold` 5개와 `warm` 5개로 각 블록의 첫 조건을 정한다.
- `rng.shuffle(first_modes)`: 먼저 실행할 조건의 순서를 섞는다.
- `order`: 해당 블록에서 시험할 암호 구성의 순서다. 블록마다 한 번 섞는다.
- `schedule.append(..., list(order))`: 두 조건에 동일한 구성 순서를 각각 복사한다. 이것이 ‘짝지은 구성 순서’다.

전체 실행에서는 `--smoke`를 사용하지 않아 10개 블록 모두 실행했다. 예를 들어 한 블록에서 구성 순서가 A → B → C이면, cold와 warm 모두 A → B → C로 측정한다. A는 하나의 KEM·서명 조합을 뜻하며 실제 블록에는 43개 구성이 있다.

계획만 만드는 것으로 끝내지 않고, 저장된 실행 기록도 다시 검사했다. 검증 코드는 [experiments/scripts/analyze_balanced.py:5–18](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/experiments/scripts/analyze_balanced.py#L5-L18)이다.

```python
d=json.loads(source.read_text());assert d['status']=='passed' and d['cleanup_ok']
schedule=d['schedule'];assert len(schedule)==20
assert sum(p['mode']=='cold' for p in schedule[::2])==5
```

```python
for a,b in zip(schedule[::2],schedule[1::2]):
 assert a['block']==b['block'] and a['configuration_order']==b['configuration_order'] and {a['mode'],b['mode']}=={'cold','warm'}
for plan,block in zip(schedule,d['rounds']):
 assert (plan['mode'],plan['block'])==(block['mode'],block['block'])
 profiles=block['profiles']; assert len(profiles)==45 and profiles[0]['sentinel'] and profiles[-1]['sentinel']
 assert [(p['kem'],p['signature']) for p in profiles[1:-1]]==[tuple(p) for p in plan['configuration_order']]
```

- `schedule[::2]`: 두 항목씩 묶인 10개 블록에서 첫 항목만 선택한다. 그중 `cold`가 5개인지 검사한다.
- `{a['mode'], b['mode']} == {'cold', 'warm'}`: 각 블록에 두 조건이 하나씩 있는지 검사한다. 따라서 나머지 첫 조건 5개는 `warm`이다.
- `a['configuration_order'] == b['configuration_order']`: 같은 블록의 두 조건이 동일한 구성 순서를 사용했는지 검사한다.
- `profiles[1:-1]` 비교: 앞뒤 기준선 감시 연결을 제외한 실제 수집 구성 순서가 계획과 일치하는지 검사한다.

프로토콜 필드와 송수신 바이트의 사후 재검사는 [experiments/scripts/analyze_balanced.py:24–30](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/experiments/scripts/analyze_balanced.py#L24-L30), 전체 3,600회와 구성·조건별 30개 분석 표본 수 검사는 [experiments/scripts/analyze_balanced.py:31–35](https://github.com/17seetwice/kpqc-tls-devops-lab/blob/77e0175d812678823b702c4611f68e8d30ec88ef/experiments/scripts/analyze_balanced.py#L31-L35)에서 수행한다. 링크와 줄 번호는 설명을 작성한 소스 커밋에 고정해 이후 코드 변경으로 위치가 달라지지 않게 했다. 실험 당시 소스 커밋은 문서 상단의 `cfd6bcc`이며, 여기의 코드 참조 커밋과 구분한다.

## 결과

| 조건 | X25519 + ECDSA | PQC 구성별 중앙값 범위 |
|---|---:|---:|
| 새 프로세스 | 1.724 ms | 3.891–12.218 ms |
| 프로세스 재사용 | 0.815 ms | 2.852–11.500 ms |

ECDSA는 Elliptic Curve Digital Signature Algorithm, PQC는 Post-Quantum Cryptography를 의미한다. 시간은 클라이언트 SSL_connect 호출 구간의 경과 시간이다.

![SMAUG 결과](ko/latency_smaug.png)

그림 1. 기준선 및 SMAUG 구성의 핸드셰이크 지연. 점은 구성·모드별 30회 중앙값이다. 두 조건 모두 전체 핸드셰이크를 수행한다. 같은 값으로 반올림되는 두 점의 미세한 차이는 실용적인 성능 차이로 해석하지 않는다.

![NTRU+ 결과](ko/latency_ntru.png)

그림 2. NTRU+ 구성의 핸드셰이크 지연. 측정·집계 및 축 범위는 그림 1과 동일하다. [English SMAUG](en/latency_smaug.png) · [English NTRU+](en/latency_ntru.png)

## 해석

전체 표본 중앙값은 43개 구성 모두 재사용 조건에서 낮았으나, 일부 구성의 차이는 매우 작다. 블록별 warm/cold 중앙값 비율의 중앙값은 PQC 구성에서 약 0.659–0.988이다. 시작 순서로 나눈 5개 블록의 부분집합에서는 2개 구성에 비율 1 이상인 경우가 있다. 따라서 모든 반복·순서에서 재사용이 항상 더 빠르다고 주장하지 않는다. 구성별 값은 `paired.csv`, 블록별 값은 `blocks.csv`에 있다.

이전 실행의 기준선은 cold 1.388 ms / warm 0.538 ms였으며 이번에는 1.724 / 0.815 ms다. 두 실행의 절대값 차이를 특정 원인으로 귀속할 자료는 부족하다. 이번 설계는 모드의 고정 순서 문제를 보완하지만 단일 인스턴스 쌍의 한 실행이므로 독립 환경·여러 날짜의 재현성 검증을 대신하지 않는다. 기존 원자료와 합산하지 않았다.

## 배포 및 정리

동일 워크플로의 로컬·AWS 게이트는 각각 63/63개 항목을 통과했다. AWS 활성 경로 표본은 245회·실패 0회였다. 이 표본은 연속 가용성 보장이 아니다. 워크플로는 34분 44초에 완료됐으며 이는 빌드·EC2 시작·전달·시험·정리 전체 시간이다. TLS 시간으로 해석하지 않는다.

자동 정리 기록은 `cleanup_complete=true`, 오류 없음이다. 별도의 AWS API (Application Programming Interface) 조회에서 서버·클라이언트 모두 stopped를 확인했다. EBS (Elastic Block Store) 볼륨은 유지되므로 저장 비용은 별도다.

## 재현

```sh
.venv/bin/python 'experiments/scripts/analyze_balanced.py' 'experiments/process-reuse/measurements.public.json' 'experiments/process-reuse'
```

`measurements.public.json`은 워크플로가 제공한 공개 원기록, `workflow.public.json`은 게이트와 정리 증적이다. `summary.csv`는 구성별 중앙값, `blocks.csv`는 블록 중앙값, `paired.csv`는 짝지은 모드 비율, `audit.json`은 검증 요약이다.
