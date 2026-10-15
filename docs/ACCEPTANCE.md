# Mosaïque — Acceptance Matrix

Every requirement is tracked as `not started`, `implemented/not verified`, `verified`, or `blocked`, with links to tests and execution evidence. Never mark verified based on a mock when the criterion requires a real system. Keep this matrix up to date per milestone.

| ID | Observable acceptance criterion | Verification type |
|---|---|---|
| AUTH-01 | New user can register/sign in/sign out via chosen proven identity solution; protected APIs reject unauthenticated requests | API + browser E2E |
| AUTH-02 | User can create organization, invite another account, accept invitation and view workspace | Integration + E2E |
| AUTH-03 | Member can belong to two orgs; org A records are not visible through org B IDs, APIs, tokens, WS or async jobs | Negative integration security |
| AUTH-04 | Removed member can no longer obtain meeting tokens/access protected meeting records; already-issued short-lived media-token revocation semantics are documented/tested | Security integration |
| MEET-01 | Two authorized accounts join same LiveKit Cloud room and hear each other, with valid mute/leave controls | Real WebRTC E2E |
| MEET-02 | Meeting ends and reappears in authenticated history after browser refresh, logout/login and backend restart | Integration + browser E2E |
| ASR-01 | Per-user audio stays in isolated Pipecat session and transcripts remain correctly attributed during overlapping speech | Recorded multi-track integration test |
| ASR-02 | Remote ASR disconnect/reconnect, join/leave, track replacement and worker cancellation do not combine participants' state; gaps become visible | Fault-injection integration |
| ASR-03 | Duplicate/revised/interim/final STT events do not create duplicate finalized segments; source-time ordering supports overlapping segments | Deterministic property/integration |
| ASR-04 | With one model loaded, run actual 1/2/4 concurrent-stream Modal/vLLM test and report p50/p95 latency, GPU memory, drops, cost assumptions, cold starts; 2s p95 is a target, not a claim | Real GPU benchmark |
| HIST-01 | Authorized user can search, view and correct a meeting transcript; unauthorized or other-tenant user cannot | API + E2E |
| AI-01 | Structured decisions/action items refer to existing transcript segment evidence and indicate uncertainty | Unit + integration |
| AI-02 | Unsupported decision/owner/deadline is omitted or flagged; approval and rejection are durable and auditable | Adversarial fixtures + integration |
| INT-01 | Only approved authorized action creates an external ticket, linked to source meeting/evidence and destination ID | Sandbox-provider integration |
| INT-02 | Retries/ambiguous provider responses reconcile before repeating writes; report guarantees and limits of provider idempotency | Fault injection + sandbox provider |
| INT-03 | Credentials and tokens are organization-scoped, encrypted/secret-managed and absent from browser responses/logs | Security tests + review |
| OPS-01 | Consent/disclosure, retention/deletion, meaningful audit trail and documented data processors exist for pilot workflows | Manual process + integration |
| OPS-02 | CI runs real lint/type/unit/integration/E2E commands; unavailable external checks are explicitly unverified, not silently passed | CI logs |
| OPS-03 | User-facing errors are actionable and durable work is recoverable after failed jobs | Fault injection + E2E |

## Expected milestone mapping

### M0 status snapshot — 15 October 2026

No enterprise criterion is verified by M0. Source reuse is not behavioral completion.
Evidence: [builder report](reports/M0_BUILD_REPORT.md); future test/exit mapping:
[ordered plan](M0_MIGRATION.md).

| IDs | Status | Evidence/remaining work |
|---|---|---|
| AUTH-01..04 | not started | Prototype token checks exist; full account/membership/revocation journeys absent |
| MEET-01 | not started | Existing peer media is not LiveKit Cloud acceptance |
| MEET-02, HIST-01 | implemented/not verified | Prototype persistence/search/correction paths; no authenticated enterprise E2E run |
| ASR-01..04 | not started | Legacy isolation tests do not prove Pipecat/Voxtral or real GPU benchmark |
| AI-01 | implemented/not verified | Existing schema/citation validation; semantic support/uncertainty not fully validated |
| AI-02, INT-01..03 | not started | Durable approval and connector workflow absent |
| OPS-01..02 | not started | Privacy/retention and real CI need implementation; baseline checks have failures |
| OPS-03 | implemented/not verified | Existing errors/retries; new worker/provider failure recovery not demonstrated |

These statuses describe the complete criteria, not partial subfeatures. Paid/live
checks are NOT RUN; M2 acceptance remains gated on authorization and real evidence.

### Milestone allocation
- Phase 0: requirements mapped, risks/unknowns recorded; no behavioral completion claim.
- M1 SaaS foundation: AUTH-01..04, meeting entities scaffold and appropriate security checks.
- M2 Live meeting/STT: MEET-01, ASR-01..04 (GPU bench can be marked blocked until approved/costed).
- M3 Meeting intelligence: MEET-02, HIST-01, AI-01..02.
- M4 Integration: INT-01..03.
- M5 Hardening: OPS-01..03 and release/pilot readiness review.

CI coverage and required live checks may evolve; changes to acceptance criteria require an explained, reviewed update, not quiet weakening.
