# KPQC TLS DevOps Lab

[한국어](README.md) | **English**

**A proof of concept that checks actual TLS connections before activating a new release and blocks candidates that violate the approved PQC configuration.**

The lab uses [`dmfive/kpqc-ossl3`](https://hub.docker.com/r/dmfive/kpqc-ossl3), an OpenSSL image integrating Korean post-quantum cryptographic algorithms.
It simulates container, certificate, and configuration changes that introduce unapproved algorithms or prevent the provider from loading.

## How it works

![KPQC deployment validation architecture](docs/architecture/en/fig1-architecture.png)

GitHub Actions builds and tests the image, then deploys it to two AWS EC2 instances over SSH.
The client connects to the candidate service over private IP. The server-side deployment gate compares the negotiated TLS parameters and certificate verification results against the policy.

- **Active:** The existing service handling connections.
- **Candidate:** A new version awaiting validation. Approval makes it active; rejection removes it and preserves the existing service.

The existing active service already uses PQC. This deployment experiment focuses on **preventing cryptographic configuration regressions during updates**.
A successful TLS handshake does not authorize deployment if the negotiated algorithms violate the policy.

[Deployment workflow](docs/architecture/en/fig2-deployment-flow.png) · [Korean architecture](docs/architecture/ko/fig1-architecture.png) · [Korean workflow](docs/architecture/ko/fig2-deployment-flow.png)

## Deployment policy and tests

The current [policy](policies/pqc-required.json) requires **TLS 1.3 · SMAUG1 · HAETAE2 · TLS_AES_256_GCM_SHA384**.
Certificate verification and connections from the required PQC client must succeed. Classical fallback is not allowed.

| Candidate configuration | Expected behavior |
| --- | --- |
| SMAUG1 + HAETAE2 | Approve and switch the active route |
| X25519 + HAETAE2 | Reject: key exchange policy mismatch |
| SMAUG1 + ECDSA | Reject: signature policy mismatch |
| Provider loading failure | Reject |

Candidates are evaluated independently. After promotion, five connections trusting only the new certificate verify the cutover.
Test evidence records negotiated parameters, verification results, and approval or rejection reasons.

## CI/CD and recorded results

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| [CI](.github/workflows/experiment.yml) | Push / pull request | Docker-based file signing, transfer, and deployment gate tests |
| [AWS deployment validation](.github/workflows/aws-deploy.yml) | Manual dispatch on main | Build and test → OIDC authentication → EC2 deployment → candidate validation and promotion → evidence and cleanup |

OIDC provides AWS credentials; SSH executes commands on EC2. Successful CI does not automatically trigger AWS deployment.

The [recorded AWS run](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/35961683618) passed **32 assertions in each of the local and AWS tests**.
The AWS active route had zero failures across 86 sampled connections. EC2 instances were stopped and temporary SSH ingress rules were removed afterward.
Correctly rejecting an invalid candidate counts as a successful test.
The [preserved JSON evidence](evidence/github-aws-35961683618.json) corresponds to commit `55795e7`.

## Run the lab and explore the code

Docker and Docker Compose are required. The base image targets `linux/amd64` and is pinned by digest.

```sh
# Test candidate approval, rejection, and active route switching
docker compose -f compose.gate.yaml run --build --rm gate

# Test file signing and TLS transfer using synthetic financial XML
docker compose run --build --rm lab
```

Results are written to `artifacts/`. For AWS execution, see the [setup guide](docs/aws-setup.en.md).

| File | Responsibility |
| --- | --- |
| [gate_suite.py](scripts/gate_suite.py) | Candidate scenarios and expected-result assertions |
| [gate_worker.py](scripts/gate_worker.py) | TLS probes, policy evaluation, and route switching |
| [ci_deploy.py](scripts/ci_deploy.py) | EC2 lifecycle, image delivery, and cleanup |
| [tls_handshake.c](scripts/tls_handshake.c) | Handshake measurement and negotiated parameter collection |
| [lab.py](scripts/lab.py) | Synthetic file signing and transfer experiments |

## Scope

The broader cryptographic experiments cover SMAUG-T and NTRU+ KEMs, and HAETAE and AIMer signatures. The deployment gate validates the representative SMAUG1 + HAETAE2 combination.
Synthetic data uses a public camt.053 XSD; it does not reproduce an actual bank's settlement operations.

The AWS setup is a temporary PoC that stops EC2 instances after each experiment; EBS volumes remain.
The TCP router uses a lab-specific route selector. Successful sampled connections do not establish a production zero-downtime SLA.
Private keys, login files, and customer transaction data are excluded from the public repository.
