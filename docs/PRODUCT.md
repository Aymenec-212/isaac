# Mosaïque — Enterprise Product Specification

## Vision
Mosaïque turns company meetings into **evidence-backed decisions and reviewed operational actions**. The product is a genuinely usable multi-user application, not a transcription demo. The first complete outcome is: **meeting → attributed transcript → supported action item → human approval → ticket in Linear or Jira → tracked status**.

## Primary journeys
1. **Workspace owner:** registers/signs in, creates an organization, invites teammates and manages permissions.
2. **Meeting organizer:** creates a meeting, controls meeting access and obtains a shareable join experience.
3. **Participants:** join a real LiveKit-hosted audio call, hear each other, mute/unmute, see other participants and live, speaker-attributed transcription.
4. **Reviewer:** returns to meeting history, examines transcript, verifies/edits decisions and action items with evidence references, approves or rejects proposed actions.
5. **Authorized integrator:** connects one organization to Linear or Jira, maps destination project/owner, performs explicit approved write, sees ticket link/status and audit trail.
6. **Admin:** manages membership, revocation, tenant settings, data retention and deletion, integration access and operational status.

## Product requirements
- Account identity and session security via a proven auth solution; sign-up/login, logout, recovery, profile, workspace membership, roles, organization switching, invitations and access revocation.
- Secure server-side authorization for **every** organization/meeting operation, including background tasks and WebSocket access. A user may belong to more than one organization.
- Full meeting lifecycle: create/invite/join/leave/end; participant state; meeting history accessible after reload; transcript storage, viewing, correction and search.
- Separate audio stream per participant; avoid diarization when identity is provided by the authenticated meeting track. Overlap must remain attributed correctly.
- Async summary/decision/action extraction with timestamps, speaker and original segment references. Distinguish decisions, proposals and unresolved questions; don't invent owners/deadlines.
- Human review and approval before creating tickets. Store linkage, provider IDs, status and immutable auditable transitions.
- Proper user-visible loading, failure, degraded and empty states; avoid UI-only simulations of backend features.
- Organization-scoped integration credentials and scope minimization; never expose them to browser clients.
- Privacy: explicit transcription/recording disclosures, configurable retention/deletion, security controls, consent requirements depending on applicable jurisdiction, regional/provider data-flow visibility.
- Extensible provider boundary for company APIs/data platforms, but **no generalized workflow engine or speculative connectors** in first release.

## Business-value differentiators
- Decisions and action items are traceable to original transcript evidence.
- Approved actions integrate into tools employees already use; no autonomous unapproved side effects.
- Follow-up meetings can refer to outstanding decisions and existing ticket status.
- Integration boundaries can adapt to company-specific APIs, permissions and operational workflows.

## Deliberate scope boundaries
- First meetings run inside Mosaïque using LiveKit Cloud. Teams/Zoom/Meet integrations are later: per-participant audio may not be available there.
- No video, AI voice bot, diarization framework, company-wide knowledge graph, or dozens of integrations in v1.
- Initially one real ticket system (choose Linear **or** Jira based on feasibility; not both by default).
- Do not claim compliance, production-readiness, zero data loss or exactly-once external effects without evidence.

## Successful pilot
Two or more users in different accounts can join the same authorized meeting, talk simultaneously, obtain reliably attributed saved transcripts, revisit history, approve one evidence-backed action and find exactly the correct ticket and audit record afterward. Cross-organization data access is blocked.
