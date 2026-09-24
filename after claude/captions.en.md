# Figure captions

**Figure 1. TLS handshake latency for the baseline and SMAUG configurations.** Points show median client SSL_connect duration across 15 connections per configuration and mode, comprising three analyzed connections in each of five rounds. Circles denote fresh processes and squares denote reused processes and SSL contexts. Warm-up connections are excluded. Every connection performs a full handshake without session resumption.

**Figure 2. TLS handshake latency for NTRU+ configurations.** Measurement conditions, aggregation and axis limits match Figure 1. Each panel shows one KEM parameter set with six signature configurations. Configurations span different security parameters and do not constitute an equal-security ranking.

**Figure 3. Handshake-window peak RSS growth for the baseline and SMAUG configurations.** Points show medians of three separate fresh-process measurements. Process RSS high-water marks are reset after initialization; the increase during the SSL call is recorded. Circles denote clients and squares denote servers. This process-level metric includes page-accounting and mapping effects and is distinct from total algorithm memory requirements.

**Figure 4. Handshake-window peak RSS growth for NTRU+ configurations.** Measurement conditions, aggregation and axis limits match Figure 3.

**Figure 5. Handshake latency across rounds for selected configurations.** Each point represents the median of three connections in one round. SMAUG1/NTRU+576 and HAETAE2/AIMer128f illustrate the cross-product of two KEM and two signature families, with the classical baseline included. Selection is not based on measured performance. All configurations appear in Figures 1–2. Fresh and reused modes were run in separate time periods; matching round numbers do not indicate simultaneous observations.

**Figure 6. TLS performance experiment architecture.** A local controller invokes instrumented clients and servers through SSH. TLS traffic uses private EC2 addresses. Endpoint records provide negotiation evidence, latency and memory observations. Performance measurements bypass the deployment router.

**Figure 7. Evidence-based deployment gate.** Probes through the router’s candidate route are evaluated against approved cryptographic policy. Accepted candidates replace the active routing target; rejection preserves the existing target. Provider availability is not a policy criterion. This figure describes the locally controlled AWS execution, not a new GitHub Actions run.
