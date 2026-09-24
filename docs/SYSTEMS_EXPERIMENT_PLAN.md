# Controlled-network and deployment-load experiments

## Scope

Run on the existing two EC2 instances in the Seoul region. Create no additional EC2 instances. Stop both instances and revoke the temporary runner SSH ingress after completion or failure. Certificate-chain experiments are outside this run.

AWS documents support for a 1500-byte MTU (Maximum Transmission Unit) on all EC2 instance types and a 1500-byte limit on Internet-gateway traffic. A 9001-byte interface in a same-AZ VPC does not make a 1500-byte comparison irrelevant. It makes the comparison a controlled sensitivity experiment. Neither condition represents the public Internet.

Source: [AWS network MTU documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/network_mtu.html).

## Experimental design

Use the same isolated Docker bridge arrangement in both MTU conditions. Change the container interface, not the EC2 host interface. The SSH management path is unaffected. Give only the experiment containers NET_ADMIN. Disable TCP segmentation/generic segmentation/generic receive offload and fail preflight if these controls are unavailable; retain the observed feature state. Record the interface MTU, qdisc configuration, and TCP_INFO values including MSS (Maximum Segment Size), path MTU and smoothed RTT (Round-Trip Time).

Representative profiles: X25519 + ECDSA P-256, and the Cartesian product of {SMAUG1, NTRU+ KEM768} and {HAETAE2, AIMer128f}. These cover four algorithm families; they are not a security-level-equivalent ranking.

| Experiment | Conditions | Repetition and endpoint |
|---|---|---|
| Network sensitivity | MTU 1500/9001; 0/5/15 ms added egress delay on **each** endpoint | Three shuffled blocks; five full handshakes per condition, first two retained as warmup; client SSL_connect latency and directional TLS message bytes |
| HRR (HelloRetryRequest) | Client first offers X25519 key share while server accepts only the target KPQC group; matching-share control; MTU1500, same three delay settings | Four KPQC profiles; three blocks; randomized control/retry order; verify exactly zero/one HRR and identical final approved group/signature |
| Concurrent service | MTU1500, no injected delay; eight prefork server workers; 1/4/16 concurrent closed-loop client processes | Three shuffled blocks; eight-second load windows after 16 server-priming connections; report completed full handshakes/s, errors, SSL_connect latency, and TCP+readiness+TLS latency |
| Deployment under load | Four concurrent clients; reject mixed-KEM candidate, then promote approved candidate | Up to 120 seconds, stopped after post-promotion observations; verify gate decisions, TLS validity and observed old/new certificate fingerprints |

The local smoke test uses fewer profiles, one block, 0/5 ms egress delay and two-second load windows. It verifies mechanics and is not an AWS performance result.

## Measurement interpretation

- The latency timer brackets SSL_connect only. TCP setup, the experimental readiness byte and JSON writing are outside that timer. A second load metric includes TCP setup, readiness waiting and TLS, so queueing is not hidden by the readiness protocol.
- The concurrent server reuses an SSL_CTX per worker. Load clients prepare a context before a shared start signal; their first handshake is included in the finite-window load measurement. Session caching and tickets remain disabled.
- Throughput includes connection setup, termination and instrumentation/file-output overhead. It describes this prefork benchmark service and generator, not nginx/Envoy capacity or isolated cryptographic operations.
- Netem injects deterministic egress delay in both directions. A configured 5 ms per endpoint corresponds nominally to 10 ms added RTT; report observed TCP RTT too. Record any offload limitation. No packet-loss experiment is included.
- Summarize each block first. Plot paired MTU conditions, no-HRR/HRR conditions and throughput against concurrency. Three within-run blocks do not establish between-instance or long-term confidence intervals.
- The deployment trial observes new connection routing under finite load. It does not prove a production availability SLA or continued application traffic on established connections.
- No new memory claim, certificate-chain claim or production-server interoperability claim is made.

## Acceptance and failure handling

Require certificate verification, TLS1.3, expected group/signature, no session resumption, expected HRR count, and client/server handshake-message byte agreement. For MTU conditions, inspect TCP MSS against the configured bound. Preserve unsuccessful attempts and subprocess exit codes; never drop them to improve throughput.

Reject a mixed KEM candidate that accepts a classical-only probe even when its broad probe negotiates PQC. Accept the approved candidate only after the actual gate validates positive and negative probes and candidate binding. Load must still be running during both decisions. Verify observed service certificate fingerprints; the rejected candidate must never appear on the active path.

Run local Docker integration checks before starting EC2. Use a bounded AWS suite and a separate always-run cleanup step. Check the actual stopped state after the workflow. Publish new numerical results for review before replacing the repository's existing result tables.
