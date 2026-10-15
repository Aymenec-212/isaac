# Mosaïque — Repository Engineering Contract

This file applies to every implementation and review in this repository. Keep it short and current; read linked specifications only when relevant.

## Source of truth
- `docs/PRODUCT.md`: product scope, users, enterprise workflows and non-goals.
- `docs/ARCHITECTURE.md`: intended boundaries, technical assumptions to verify, and trust boundaries.
- `docs/ACCEPTANCE.md`: requirement IDs and observable behavior. Changes must name the affected IDs.
- `docs/MILESTONES.md`: milestone ordering and exit conditions.
- `docs/QUALITY_GATES.md`: verification and milestone reporting.
- `docs/MODAL_REFERENCE.md`: findings from the earlier Voxtral deployment (not a source of credentials).
- `docs/decisions/`: accepted ADRs, when created.

## Engineering rules
- Prefer deep modules with small interfaces; hide real complexity and mutable state within clear owners.
- Avoid pass-through wrappers, premature generic frameworks, god classes, unnecessary services and duplicated sources of truth.
- Keep business authorization and invariants separate from HTTP handlers, LiveKit/Pipecat adapters, vLLM protocols and provider SDKs.
- Use Pipecat upstream functionality before building custom audio/protocol machinery; isolate each participant's STT state. Shared GPU inference does NOT mean shared ASR session state.
- LiveKit Cloud hosts calls; application owns accounts, organizations, permissions, meetings, transcript state and business actions.
- Treat AI-extracted content as untrusted. External writes require permission and explicit approval. Preserve transcript provenance.
- Enforce tenant isolation server-side everywhere (including WebSockets, room-token issuance, background jobs and integrations).
- Design bounded async queues, cancellation, teardown, error visibility and recovery. Never silently drop speech or duplicate ticket actions.
- Do not invent supported vLLM batching features; verify on pinned versions with measurements.
- Never commit secrets, real customer recordings, production credentials or local-reference source copies.

## Work protocol
1. Locate and read the relevant requirements/ADRs and inspect neighboring code.
2. State scope and acceptance IDs for any milestone-sized change; introduce only meaningful interfaces.
3. Add or update behavioral tests, including negative cases and resource cleanup.
4. Run actual repo verification commands; do not invent success or obscure skipped checks.
5. Inspect the diff for boundary violations, needless abstractions and deletion of working functionality.
6. Update verification evidence and concise docs, then commit to the milestone branch.

## Definition of done
An acceptance criterion is **done** only with observed behavior and tests. Each milestone needs a diff, a test/evidence report, known limitations, an independent review and human approval before merge. CI, type checks and code review are complementary, not interchangeable.

Do not perform destructive migrations, deploy paid services, grant credentials, invoke external production writes or merge without explicit approval.

## Codex reviewer-specific instruction
When asked to review: be independent, findings-first, cite file/line and acceptance ID, distinguish verified evidence from claims. Do not modify application source. Look for real failure modes and architecture regressions, not stylistic preferences.
