# M0-001: Modular monolith with separately owned media lifecycle

Status: Proposed, 2026-10-15. IDs: AUTH-03, MEET-01..02, ASR-01..04, OPS-03.

Keep FastAPI, React and PostgreSQL; introduce coherent application owners rather
than rewrite business behavior into microservices. HTTP, media and jobs may run
as separate processes sharing application code. Pipecat owns upstream media/frame
lifecycle; our media adapter owns identity routing and isolated STT generations.
vLLM runs separately on Modal. See [design](../M0_DESIGN.md).

This hides protocol and scheduling changes from transcript/history/review. It
requires leases/fencing instead of the current process-global registry assumption.
Reject both a shared stateful STT pipeline for all speakers and a general event bus.
Retain old ingress behind explicit meeting mode until parity; no automatic fallback.
The proposed runtime is contingent on Pipecat version and real GPU evidence.

Review gate: agree module ownership, verify no unnecessary service interfaces,
and resolve upstream resampler/publication risks before M2 implementation.
