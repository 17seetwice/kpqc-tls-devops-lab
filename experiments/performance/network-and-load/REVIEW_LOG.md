# Implementation and validation log

- Design review: isolate MTU/delay from the host management interface; keep both MTU treatments on the same bridge topology; bound the run and retain unconditional EC2 cleanup.
- Measurement review: distinguish SSL_connect latency from TCP/readiness queueing; report finite-window service throughput including instrumentation; inspect actual MSS/RTT and HRR, rather than assuming the requested condition took effect.
- Initial local integration: MTU1500/9001 and HRR control/induction passed for both KPQC KEM families. Load launch found an overly restrictive tag validator (underscore in NTRU+ name); fixed before any AWS start.
- Second local integration (local-systems-20260924T145349Z): 49 assertions passed, including concurrent clients, mixed-KEM rejection and approved-candidate promotion under load. No cleanup errors. This run used no injected delay.
- Existing gate regression (local-gate-20260924T145257Z): 63 assertions passed. Policy unit tests: 6 passed; cleanup failure-path tests: 4 passed.
- Additional preflight requirements: 5 ms egress-delay treatment, offload-disabled checks, eight surviving server workers, and exact SSL-return timestamp for the load queueing metric. These are verified by the final smoke run before AWS execution.

## First AWS execution: 36016712344

The full network (90 condition blocks), HRR (72 blocks) and concurrent throughput (45 windows) matrices completed. The final deployment assertion failed: only the old certificate was observed, and all four load processes exited with code 2 after 70.857 seconds (26,701 recorded successful handshakes). This trial is **not** a successful rollout-under-load result. The process stderr was not exported in that revision, so the exact cause of those fatal exits cannot be established from this artifact alone. Both EC2 instances were independently confirmed stopped.

The controller also rewrote the accumulated full dataset (429 MiB public JSON) at every assertion; the logs show increasing control-step durations. The follow-up writes completed blocks once and lightweight progress checkpoints, exports endpoint stderr/resource diagnostics, verifies live load workers, waits for the new certificate, and sustains traffic for another 60 seconds. Only the deployment trial is rerun; already collected performance observations retain their original execution identity.

## Build-only retry failures

Runs 36023197203 and 36024092435 failed before AWS authentication/start: HTTP download of libexpat1 returned 404 despite index refresh. At 16:03–16:04 UTC, direct requests reproduced HTTP 404 and HTTPS 200 for the same official package path. Apt sources were changed to HTTPS; the precise upstream/cache cause remains undetermined. Both EC2 instances were independently confirmed stopped.

## Successful separate rollout: 36025021206

Source c9ebcfa. HTTPS package installation passed locally and on the runner. AWS rollout assertions: 8/8. Four clients exited 0 with empty load stderr, completing 24,504 handshakes in 73.760747107 seconds: old certificate 3,847; new certificate 20,657. The offline audit verified more than 60 seconds between first and last new-certificate completions. Both endpoints reported zero OOM events. Both EC2 instances were independently confirmed stopped.

Diagnostic review: negative probes intentionally generated TLS errors. Former active-v1 workers logged accept EAGAIN exits after becoming idle; the benchmark exits on accept failure with a socket receive timeout. Forward promotion passed, but keeping the former service ready for immediate rollback is not established. This does not retrospectively identify the exact fatal error in the first trial, whose stderr was not preserved.

Final review: source/image identities remain separate for performance and retry; every retained connection was checked for expected negotiated codes, authentication and no resumption; block counts and all plotted aggregates were recomputed; the final report does not replace the public main result tables.
