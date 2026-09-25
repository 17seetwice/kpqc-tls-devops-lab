# TLS handshake latency with fresh and reused processes

[한국어](README.md) | English

Run: `aws-extended-20260924T134811Z` · Source: `cfd6bcc` · [GitHub Actions evidence](https://github.com/17seetwice/kpqc-tls-devops-lab/actions/runs/36007402798)

## What is being compared?

The experiment compares TLS handshake latency for the same cryptographic configuration when the test program starts afresh for each connection versus when a running process creates another connection.

### What is a process?

A program is an executable file; a process is a running instance of that program. Starting `tls_handshake` gives it memory, execution state and a PID (Process ID). Separate executions of the same program can create different processes.

Here, processes are the server/client test programs. EC2 instances and containers are not recreated for every connection. An open port alone does not establish whether a process is being reused.

### Fresh versus reused processes

- Fresh process (cold): start a new client program for each connection. The listening server parent forks a child per connection; that child prepares the TLS configuration and performs the handshake.
- Reused process (warm): retain the process and OpenSSL configuration object (`SSL_CTX`) within repeated measurements of one configuration. Perform two preparation connections, then analyze three connections.
- Both modes: create a new TCP (Transmission Control Protocol) connection and per-connection TLS object each time, performing a full handshake. TLS session resumption via session tickets is disabled.

```text
Fresh:  start and configure → connect and complete handshake → exit → start again
Reused: start and configure → connect and complete handshake → close connection → connect again in the same process
```

Reuse is scoped to repeated connections for one configuration, not one process for all algorithms. Cold does not mean that operating-system caches were forcibly cleared.

### Why change the measurement order?

If fresh-process trials always run first, reused-process trials are always measured later. CPU load or cache state may change during that interval, mixing execution-time effects with process-reuse effects.

A block pairs one measurement sequence for each mode. Ten blocks were run:

- Five blocks: fresh-process mode → reused-process mode.
- Five blocks: reused-process mode → fresh-process mode.
- The block order was shuffled. Within each block, the 43 configurations were randomized, with the same configuration order used for both modes.

This is balanced execution order: both modes start first equally often. Process reuse is the comparison of interest; balancing is a design choice that reduces systematic first/last ordering bias.

### What does the timer include?

Process creation, explicit TLS configuration, TCP establishment and the experimental readiness signal precede timing. The main metric is elapsed time around the client's `SSL_connect` call, not total program startup time. Initialization first performed inside the call and cache-state effects may still contribute.

## Design and validation

Two existing EC2 (Elastic Compute Cloud) instances performed sequential TLS (Transport Layer Security) connections. No additional instances were created. Ten paired blocks used five cold-first and five warm-first assignments in shuffled order. Configuration order was randomized within a block and shared across its two modes. Each of the 43 configurations has 30 analyzed connections per mode.

All 3,600 collected connections passed the protocol checks; 2,580 enter latency analysis and 1,020 are warm-up or sentinel observations. The audit checked negotiated group/signature identifiers, certificate verification, TLS version and cipher, disabled session resumption, zero HRR (HelloRetryRequest), matching directional message bytes, mode-order balance and paired configuration order. No new memory experiment was performed.

## Results

| Condition | X25519 + ECDSA | Range of PQC configuration medians |
|---|---:|---:|
| Fresh process | 1.724 ms | 3.891–12.218 ms |
| Reused process | 0.815 ms | 2.852–11.500 ms |

ECDSA denotes Elliptic Curve Digital Signature Algorithm and PQC denotes Post-Quantum Cryptography. Latency covers the client SSL_connect call.

![SMAUG latency](en/latency_smaug.png)

Figure 1. Baseline and SMAUG handshake latency. Each point is the median of 30 connections per configuration and mode. Both modes perform full handshakes. Tiny differences between points rounding to the same value should not be interpreted as practical improvements.

![NTRU+ latency](en/latency_ntru.png)

Figure 2. NTRU+ handshake latency. Measurement conditions, aggregation and axis limits match Figure 1.

## Interpretation

Pooled within-run medians were lower for the reused-process mode in all 43 configurations, but some differences were very small. Across PQC configurations, the median of ten paired block ratios (warm/cold) ranged from approximately 0.659 to 0.988. When the blocks were split by starting mode, two configurations had a subgroup median ratio of at least one. Reuse is therefore not claimed to be faster in every block or ordering. See `paired.csv` and `blocks.csv`.

The previous run had baseline medians of 1.388 ms (cold) and 0.538 ms (warm), compared with 1.724 and 0.815 ms here. Available evidence does not identify a single cause of this between-run difference. Balanced ordering addresses the original fixed-order design but does not replace replication across dates or independent instance pairs. The two datasets were not pooled.

## Deployment and cleanup

Local and AWS gate runs each passed 63/63 assertions. The AWS active-route monitor recorded 245 samples with zero failures; this does not establish continuous availability. The workflow took 34 minutes 44 seconds, including build, instance startup, transfer, tests and cleanup. This is not TLS handshake time.

Cleanup evidence reports completion with no errors. A separate AWS API (Application Programming Interface) read confirmed that both instances were stopped. EBS (Elastic Block Store) volumes remain provisioned and have separate storage charges.

## Reproduction

```sh
.venv/bin/python 'after_claude/scripts/analyze_balanced.py' 'after_claude/balanced/measurements.public.json' 'after_claude/balanced'
```

`measurements.public.json` contains the public workflow measurements; `workflow.public.json` contains gate and cleanup evidence. `summary.csv`, `blocks.csv` and `paired.csv` hold configuration medians, block medians and paired-mode ratios. `audit.json` records the validation summary.
