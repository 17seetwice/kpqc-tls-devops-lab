# KPQC TLS DevOps Lab

[한국어](README.md) | English

An OpenSSL-based project that measures KPQC TLS handshake performance, admits deployments using cryptographic and performance checks, and restores a previously approved service after a failure.

The project uses [`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3). Performance experiments cover SMAUG and NTRU+ KEMs (Key Encapsulation Mechanisms), with HAETAE and AIMer signatures. The migration and recovery experiment uses SMAUG1 + HAETAE2.

## Validation objectives and experimental design

The objective is to measure KPQC TLS costs under bounded resources and determine whether observed cryptographic settings and response performance can govern deployment admission and recovery. The experiments separate performance measurement, cryptographic enforcement and deployment recovery.

### 1. Handshake cost across configurations

Method and criteria: Compare 42 combinations of seven SMAUG/NTRU+ parameter sets and six HAETAE/AIMer parameter sets against X25519 + ECDSA P-256. Record full-handshake latency, CPU time on both endpoints and message bytes; measure memory separately.

Observed outcome: The initial run analyzed 1,290 timing and 129 memory samples. The follow-up balanced fresh/reused-process order and analyzed 2,580 timing samples. Configuration-level latency is summarized below.

### 2. Network and concurrency effects

Method and criteria: Compare five representative configurations at MTU (Maximum Transmission Unit) 1500/9001 and added round-trip delay 0/10/30 ms. Compare HRR (HelloRetryRequest) with a control using the same final algorithms. Measure throughput with eight server workers and 1/4/16 client processes.

Observed outcome: At 30 ms added delay, SMAUG1 + AIMer128f measured 62.576 ms at MTU 1500 and 34.128 ms at MTU 9001. HRR added approximately 31 ms. Concurrent-load tests validated 273,091 connections.

### 3. Rejection of forbidden cryptographic settings

Method and criteria: Require observed TLS 1.3, SMAUG1, HAETAE2, the specified cipher suite and successful certificate verification. Classical-only key exchange/signature and TLS 1.2 probes must fail. Check evidence freshness and binding to candidate, certificate fingerprint, image and policy.

Observed outcome: Candidates accepting both KPQC and classical connections were rejected despite successful KPQC connectivity. The cryptographic gate passed 63 assertions, including mismatched or stale evidence and probe errors.

### 4. Performance-based deployment admission

Method and criteria: Test each candidate at 10 arrivals/s for three 10-second windows. Every window requires failure rate ≤1%, ≥99% completion within 200 ms, successful completion p95 ≤200 ms and generator lateness p95 ≤50 ms.

Observed outcome: All three candidates completed 300 successful TLS connections each. Two normal candidates were admitted; the candidate with an injected 350 ms delay passed cryptographic checks but was rejected on performance.

### 5. Deployment under load and recovery after failure

Method and criteria: Test routing between healthy services separately from stopping the new service's processes. Recheck the previous approved KPQC service's current TLS health and certificate before restoring routing.

Observed outcome: The deployment retest observed zero failures across 24,504 attempts. The separate fault experiment detected failure in 1.596 s and verified recovery in 2.951 s, with 21 failures among 150 attempts.

### 6. Automation and execution traceability

Method and criteria: Connect image build/test, AWS execution, policy decisions, evidence collection and cleanup through GitHub Actions. Preserve source commits, image identifiers, certificate fingerprints and raw records.

Observed outcome: The final AWS run passed 63 cryptographic-gate and 24 migration/admission/recovery assertions. Both EC2 instances were stopped and temporary SSH ingress was removed afterward.

For example, a candidate may change from SMAUG1-only to accepting both SMAUG1 and X25519. A successful KPQC probe alone would miss this regression. The gate also attempts an X25519-only connection and rejects the candidate if that connection succeeds. A cryptographically compliant candidate is likewise rejected if it exceeds the response-performance limits.

Performance comparisons report observations; deployment decisions apply criteria fixed before testing. Connection counts and latencies from different runs are not pooled. Network latency values above are medians of three block medians. The [network and load report](after_claude/systems/README.en.md) preserves detailed conditions and the failed initial deployment attempt.

The [full walkthrough (Korean)](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.md) explains the objectives, environment, methods and results. Download its [HTML version](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.html) to view it in a browser.

## Environment and measurement boundaries

The server and client each run on one m7i.large EC2 instance in the same Seoul availability zone, communicating over private IPv4. Each experimental container is limited to 2 CPUs and 512 MiB memory. Concurrent client counts refer to processes within the client instance, not additional EC2 instances.

| Experiment | Network conditions | Configurations |
|---|---|---|
| Initial and balanced-order measurements | Docker host networking, interface MTU 9001 | SMAUG 1/3/5 and NTRU+ 576/768/864/1152 × HAETAE 2/3/5 and AIMer 128f/192f/256f, plus the classical baseline |
| Network and concurrent load | Docker bridge; MTU 1500/9001 comparison; consult individual reports for each trial | Classical baseline and {SMAUG1, NTRU+ KEM768} × {HAETAE2, AIMer128f} |
| Performance admission and recovery | Docker bridge, MTU 1500 | Migration from X25519 + ECDSA P-256 to SMAUG1 + HAETAE2 |

Performance comparisons include different security parameter sets and do not rank algorithms at equivalent security levels. Separately, deployment tests fix SMAUG1 + HAETAE2 as the approved combination. Deploying another KPQC combination requires updating the policy.

| Metric | Boundary and interpretation |
|---|---|
| TLS handshake latency | Monotonic elapsed time around the client's `SSL_connect`. Excludes TCP establishment, explicit initialization and the experimental readiness signal; lazy initialization inside the call may remain. |
| Server/client CPU time | Difference in user plus system CPU time around each process's SSL call. Distinct from elapsed time that includes network waiting. |
| Handshake-interval peak RSS (Resident Set Size) increase | Reset the RSS high-water mark after initialization and measure its increase during the call in a separate run. Three samples per configuration; not total memory requirements or a fixed per-connection cost. |
| Handshake message size | Sum of message-callback send/receive lengths. Excludes TLS record and TCP/IP headers and retransmissions from wire traffic accounting. |

Clients explicitly trust the self-signed server certificate and verify its hostname. Authentication is server-only, without mTLS (Mutual TLS). Experimental readiness and deployment-route selection occur outside the TLS call. This connection procedure and custom TLS identifiers assume test programs using the same image.

## TLS handshake performance

The balanced follow-up analyzed 2,580 connections: 43 configurations × 2 modes × 30 measurements. Preparation and monitoring connections were excluded from analysis.

| Execution mode | X25519 + ECDSA P-256 median | Range of KPQC configuration medians |
|---|---:|---:|
| Fresh process | 1.724 ms | 3.891–12.218 ms |
| Reused process | 0.815 ms | 2.852–11.500 ms |

Measurements span the client's `SSL_connect` call. Each range gives the smallest and largest median across 42 KPQC configurations. In fresh-process mode, the server forks a child per connection. Reused-process mode still creates a new connection and performs a full TLS handshake each time. [Methods and complete results](after_claude/balanced/README.en.md)

## Deployment lifecycle

![Deployment and recovery](after_claude/release/architecture.en.png)

1. Initial KPQC deployment candidate replaces X25519 + ECDSA P-256 with SMAUG1 + HAETAE2.
2. Subsequent update candidate retains the algorithms but uses a new server certificate and a separate server process. Business functionality is unchanged.
3. Recovery injects a failure into the new deployment, checks the previous service's current TLS connectivity, certificate and cryptographic policy, then restores routing to that approved service. KPQC remains in use.

Successful TLS connectivity does not imply deployment approval. Observed cryptographic settings and performance must both satisfy policy. Policy violations or missing evidence preserve the current service.

## Performance-based admission results

Two m7i.large EC2 (Elastic Compute Cloud) instances in the same Seoul availability zone; each container has 2 CPUs and 512 MiB memory, with Docker bridge networking and MTU (Maximum Transmission Unit) 1500. Each candidate receives 10 arrivals/s for three 10-second windows: 300 attempts.

The SLO (Service Level Objective) is a synthetic target fixed before testing. Every window requires ≤1% failed attempts, ≥99% successful completion within 200 ms and successful completion p95 ≤200 ms. Load-generator lateness p95 must be ≤50 ms.

| Candidate | Cryptographic checks | Completion p95 by window | Decision |
|---|---|---|---|
| Candidate with injected 350 ms delay | Pass | 382.56 / 382.46 / 381.96 ms | Reject |
| Initial KPQC deployment candidate | Pass | 32.99 / 33.19 / 33.28 ms | Admit |
| Subsequent update candidate | Pass | 33.20 / 32.56 / 32.74 ms | Admit |

Completion time spans scheduled arrival to test-client process exit, including initialization, TCP and TLS. Pure TLS (Transport Layer Security) handshake latency is recorded separately around `SSL_connect`. The 95th percentile, p95, is the value at or below which 95% of observations fall.

From the fault-injection request, detection took 1.596 s and verified recovery took 2.951 s. The 150 fault-window attempts included 21 failures; the final 20 all succeeded on the restored service. This is not a zero-downtime result.

[English report](after_claude/release/README.en.md) · [한국어 보고서](after_claude/release/README.md) · [Figure gallery](after_claude/release/gallery.html) · [Evidence audit](after_claude/release/audit.json)

## Cryptographic policy and CI/CD

Policy requires TLS 1.3, SMAUG1, HAETAE2 and TLS_AES_256_GCM_SHA384. KEM and signature identifiers are checked separately from the cipher suite. Tests cover classical KEM/signature acceptance, TLS 1.2, certificate verification results, mismatched certificate fingerprints or stale evidence and probe errors.

GitHub Actions builds and tests the image locally, obtains temporary AWS credentials through OIDC (OpenID Connect), and uses SSH (Secure Shell) to deploy the identical image to the existing server and client. It saves evidence, stops both EC2 instances and removes temporary SSH ingress. Push-triggered CI does not start EC2 instances.

[The AWS execution](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36032662708) passed 63 cryptographic-gate assertions and 24 migration, admission and recovery assertions. Experiment source `c232f7d` is distinct from subsequent documentation and CI fixes. Both instances were confirmed stopped by the workflow and an independent AWS query.

## Other experiments and reproduction

| Experiment | Documentation |
|---|---|
| Handshake, CPU and memory across 43 configurations | [Environment](after_claude/01_environment.md) · [Methods](after_claude/02_methods.md) · [Results](after_claude/03_results.md) · [English captions](after_claude/captions.en.md) |
| Balanced fresh/reused-process execution order | [English](after_claude/balanced/README.en.md) · [한국어](after_claude/balanced/README.md) |
| MTU, network delay, HelloRetryRequest, concurrency and deployment under load | [English](after_claude/systems/README.en.md) · [한국어](after_claude/systems/README.md) |
| Migration, performance admission and automatic recovery | [Plan](docs/RELEASE_EXPERIMENT_PLAN.md) · [English](after_claude/release/README.en.md) · [한국어](after_claude/release/README.md) |

Experiments have different environments and measurement boundaries; consult each report's conditions and execution records. Download the repository to open HTML reports and galleries in a browser.

Evidence entry points: [initial summary CSV](after_claude/data/summary.csv), [balanced summary CSV](after_claude/balanced/summary.csv), [cryptographic-gate records](after_claude/data/gate.public.json) and [final deployment raw records](after_claude/release/measurements.public.json). Figure galleries cover [initial measurements](after_claude/gallery.html), [balanced order](after_claude/balanced/gallery.html), [network/load](after_claude/systems/gallery.html) and [deployment/recovery](after_claude/release/gallery.html).

Re-evaluate the public deployment records without running AWS. Run from the repository root; the command writes an audit summary to the specified directory.

```sh
python3 scripts/audit_release.py after_claude/release/measurements.public.json --out /tmp/kpqc-release-audit
```

The following commands run policy tests and a local Docker integration test. Docker, Compose and Linux amd64 (x86-64) are required. The base image is pinned by its SHA-256 content digest so that a different image under the same tag is not substituted.

```sh
python3 scripts/test_gate_policy.py
python3 scripts/test_release_policy.py
python3 scripts/test_ci_deploy.py
docker compose -f compose.gate.yaml run --build --rm gate
```

For AWS measurements, follow the [setup guide](docs/aws-setup.en.md) and use the [manual workflow](.github/workflows/aws-deploy.yml). Select `balanced_latency` for balanced execution order, `systems_experiments` for network/concurrent load, or `release_lifecycle` for migration/admission/recovery. Local integration tests use loopback and do not reproduce the two-instance AWS performance measurements.

Core code: [TLS instrumentation](scripts/tls_handshake.c), [cryptographic policy](scripts/gate_policy.py), [performance policy](scripts/release_policy.py), [migration/recovery experiment](scripts/release_experiments.py), [AWS lifecycle](scripts/ci_deploy.py). [AWS setup guide](docs/aws-setup.en.md)

## Scope of the results

The injected fault stops server processes; the previous approved service remains on the same EC2 instance. The experimental TCP router changes destinations for new connections. Production load-balancer draining and instance or availability-zone failure recovery were not tested.

In the final deployment experiment, private keys reside in the server container’s temporary memory filesystem (`tmpfs`) and are removed with the container during cleanup. Only public trust certificates are supplied to the client. A separate production key-management system is not implemented.

Repeated samples come from executions on the same instance pair. Independent replication across dates and instance pairs is outside the evaluated scope. The controller collecting and evaluating evidence is a trusted component.

Results describe the project OpenSSL image under bounded laboratory load with directly trusted server certificates. Production PKI (Public Key Infrastructure) chains, long-term availability, financial transaction preservation and interoperability with other TLS implementations are outside the verified scope. EBS (Elastic Block Store) volumes remain after EC2 shutdown.
