# Implementation and validation log

- Design review: isolate MTU/delay from the host management interface; keep both MTU treatments on the same bridge topology; bound the run and retain unconditional EC2 cleanup.
- Measurement review: distinguish SSL_connect latency from TCP/readiness queueing; report finite-window service throughput including instrumentation; inspect actual MSS/RTT and HRR, rather than assuming the requested condition took effect.
- Initial local integration: MTU1500/9001 and HRR control/induction passed for both KPQC KEM families. Load launch found an overly restrictive tag validator (underscore in NTRU+ name); fixed before any AWS start.
- Second local integration (local-systems-20260924T145349Z): 49 assertions passed, including concurrent clients, mixed-KEM rejection and approved-candidate promotion under load. No cleanup errors. This run used no injected delay.
- Existing gate regression (local-gate-20260924T145257Z): 63 assertions passed. Policy unit tests: 6 passed; cleanup failure-path tests: 4 passed.
- Additional preflight requirements: 5 ms egress-delay treatment, offload-disabled checks, eight surviving server workers, and exact SSL-return timestamp for the load queueing metric. These are verified by the final smoke run before AWS execution.
