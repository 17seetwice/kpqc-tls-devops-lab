# KPQC TLS DevOps Lab

[한국어](README.md) | **English**

An OpenSSL-based project that **measures KPQC TLS handshake performance, admits deployments using cryptographic and performance checks, and restores a previously approved service after a failure**.

The project uses [`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3). Performance experiments cover SMAUG and NTRU+ KEMs (Key Encapsulation Mechanisms), with HAETAE and AIMer signatures. The migration and recovery experiment uses SMAUG1 + HAETAE2.

## Research questions and tests

| Question | Method |
|---|---|
| How do cryptographic configurations and process reuse affect handshake cost? | Compare 42 KPQC combinations and one classical baseline, balancing fresh/reused-process execution order. Both modes perform full handshakes without session resumption. |
| Is successful KPQC connectivity sufficient for deployment? | Require approved connections to succeed and forbidden connections to fail. A candidate accepting both SMAUG1 and X25519 is rejected even when its KPQC connection succeeds. |
| What if a cryptographically compliant candidate is slow or fails after deployment? | Apply fixed-arrival-rate performance checks, then recheck the previous approved KPQC service before restoring routing after a process failure. |

The [full walkthrough (Korean)](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.md) explains the objectives, environment, methods and results. Download its [HTML version](docs/lab-meeting/PROJECT_WALKTHROUGH.ko.html) to view it in a browser.

## TLS handshake performance

The balanced follow-up analyzed 2,580 connections: 43 configurations × 2 modes × 30 measurements. Preparation and monitoring connections were excluded from analysis.

| Execution mode | X25519 + ECDSA P-256 median | Range of KPQC configuration medians |
|---|---:|---:|
| Fresh process | 1.724 ms | 3.891–12.218 ms |
| Reused process | 0.815 ms | 2.852–11.500 ms |

Measurements span the client's `SSL_connect` call. Each range gives the smallest and largest median across 42 KPQC configurations. In fresh-process mode, the server forks a child per connection. Reused-process mode still creates a new connection and performs a full TLS handshake each time. [Methods and complete results](after_claude/balanced/README.en.md)

## Deployment lifecycle

![Deployment and recovery](after_claude/release/architecture.en.png)

1. **Initial KPQC deployment candidate** replaces X25519 + ECDSA P-256 with SMAUG1 + HAETAE2.
2. **Subsequent update candidate** retains the algorithms but uses a new server certificate and a separate server process. Business functionality is unchanged.
3. **Recovery** injects a failure into the new deployment, checks the previous service's current TLS connectivity, certificate and cryptographic policy, then restores routing to that approved service. KPQC remains in use.

**Successful TLS connectivity does not imply deployment approval.** Observed cryptographic settings and performance must both satisfy policy. Policy violations or missing evidence preserve the current service.

## Performance-based admission results

Two m7i.large EC2 (Elastic Compute Cloud) instances in the same Seoul availability zone; each container has 2 CPUs and 512 MiB memory, with Docker bridge networking and MTU (Maximum Transmission Unit) 1500. Each candidate receives 10 arrivals/s for three 10-second windows: 300 attempts.

The SLO (Service Level Objective) is a synthetic target fixed before testing. Every window requires ≤1% failed attempts, ≥99% successful completion within 200 ms and successful completion p95 ≤200 ms. Load-generator lateness p95 must be ≤50 ms.

| Candidate | Cryptographic checks | Completion p95 by window | Decision |
|---|---|---|---|
| Candidate with injected 350 ms delay | Pass | 382.56 / 382.46 / 381.96 ms | Reject |
| Initial KPQC deployment candidate | Pass | 32.99 / 33.19 / 33.28 ms | Admit |
| Subsequent update candidate | Pass | 33.20 / 32.56 / 32.74 ms | Admit |

Completion time spans **scheduled arrival to test-client process exit**, including initialization, TCP and TLS. Pure TLS (Transport Layer Security) handshake latency is recorded separately around `SSL_connect`. The 95th percentile, p95, is the value at or below which 95% of observations fall.

From the fault-injection request, **detection took 1.596 s and verified recovery took 2.951 s**. The 150 fault-window attempts included 21 failures; the final 20 all succeeded on the restored service. This is not a zero-downtime result.

[English report](after_claude/release/README.en.md) · [한국어 보고서](after_claude/release/README.md) · [Figure gallery](after_claude/release/gallery.html) · [Evidence audit](after_claude/release/audit.json)

## Cryptographic policy and CI/CD

Policy requires TLS 1.3, SMAUG1, HAETAE2 and TLS_AES_256_GCM_SHA384. KEM and signature identifiers are checked separately from the cipher suite. Tests cover classical KEM/signature acceptance, TLS 1.2, certificate verification results, mismatched certificate fingerprints or stale evidence and probe errors.

GitHub Actions builds and tests the image locally, obtains temporary AWS credentials through OIDC (OpenID Connect), and uses SSH (Secure Shell) to deploy the identical image to the existing server and client. It saves evidence, stops both EC2 instances and removes temporary SSH ingress. Push-triggered CI does not start EC2 instances.

[The AWS execution](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36032662708) passed **63 cryptographic-gate assertions and 24 migration, admission and recovery assertions**. Experiment source `c232f7d` is distinct from subsequent documentation and CI fixes. Both instances were confirmed stopped by the workflow and an independent AWS query.

## Other experiments and reproduction

| Experiment | Documentation |
|---|---|
| Handshake, CPU and memory across 43 configurations | [Environment](after_claude/01_environment.md) · [Methods](after_claude/02_methods.md) · [Results](after_claude/03_results.md) · [English captions](after_claude/captions.en.md) |
| Balanced fresh/reused-process execution order | [English](after_claude/balanced/README.en.md) · [한국어](after_claude/balanced/README.md) |
| MTU, network delay, HelloRetryRequest, concurrency and deployment under load | [English](after_claude/systems/README.en.md) · [한국어](after_claude/systems/README.md) |
| Migration, performance admission and automatic recovery | [Plan](docs/RELEASE_EXPERIMENT_PLAN.md) · [English](after_claude/release/README.en.md) · [한국어](after_claude/release/README.md) |

Experiments have different environments and measurement boundaries; consult each report's conditions and execution records. Download the repository to open HTML reports and galleries in a browser.

Docker, Compose and a Linux amd64 environment are required. The base image is pinned by SHA-256 digest.

```sh
python3 scripts/test_gate_policy.py
python3 scripts/test_release_policy.py
python3 scripts/test_ci_deploy.py
docker compose -f compose.gate.yaml run --build --rm gate
```

Core code: [TLS instrumentation](scripts/tls_handshake.c), [cryptographic policy](scripts/gate_policy.py), [performance policy](scripts/release_policy.py), [migration/recovery experiment](scripts/release_experiments.py), [AWS lifecycle](scripts/ci_deploy.py). [AWS setup guide](docs/aws-setup.en.md)

The injected fault stops server processes; the previous approved service remains on the same EC2 instance. The experimental TCP router changes destinations for new connections. Production load-balancer draining and instance or availability-zone failure recovery were not tested.

In the final deployment experiment, private keys reside in the server container’s temporary memory filesystem (`tmpfs`) and are removed with the container during cleanup. Only public trust certificates are supplied to the client. A separate production key-management system is not implemented.

Results describe the project OpenSSL image under bounded laboratory load with directly trusted server certificates. Production PKI (Public Key Infrastructure) chains, long-term availability, financial transaction preservation and interoperability with other TLS implementations are outside the verified scope. EBS (Elastic Block Store) volumes remain after EC2 shutdown.
