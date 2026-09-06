# Mosaïque — Future Architecture: Media Plane Options

**Version:** 2.0 (rescoped)
**Date:** 2026-09-03
**Recorded as:** ADR-12
**Status: NON-NORMATIVE. This document does not govern the prototype.**

---

## 0. What this document is, and what it is not

This is a **research record and an option analysis for a product question that is not yet decided**. It exists so that the work already done is not lost, and so that when the question does need answering, the analysis is on the shelf rather than started from scratch.

**It does not change the prototype.** The normative source for what is being built now is the **Technical Specification v0.1**, as reconciled by the Implementation Blueprint. The prototype scope is unchanged:

- independent per-participant audio streams over browser WebSocket;
- realtime transcription, participant attribution, transcript persistence;
- meeting finalization and asynchronous meeting intelligence;
- replay/testing harness; `FakeRecognizer` and `FakeLLMProvider` first, then real Kyutai;
- single-host Docker Compose, Level 1 maturity;
- **no external conferencing-platform integration, no LiveKit, no SFU.**

An earlier revision of this document recommended a "commercial architecture" and demoted the prototype's ingress to a "dev tool". That was scope creep: it converted an open product hypothesis into a settled decision and let a future question reorder present work. **That framing is withdrawn.** Nothing below is a decision. Everything below is an option with an associated test.

### What changed in the prototype as a result of this research

Two things only, and both are recorded in the Implementation Blueprint, not here:

1. **A minimal ingress seam** (blueprint D-04) so the browser capture path can later be replaced without touching the meeting runtime, ASR, transcript, persistence, or intelligence layers. One implementation, one added enum column. It is a boundary, not a framework.
2. **Confirmation of Kyutai facts** the specification had assumed, plus one latency technique worth using (blueprint D-05).

Nothing else from this document touches the prototype, its slice order, or its spikes.

---

## 1. The question this document is for

> When Mosaïque needs to work in meetings that Mosaïque did not create, where does the audio come from?

The prototype does not have to answer this. It captures audio directly in the browser, which is sufficient to prove that realtime audio → ASR → attribution → transcript → intelligence works end to end. The question becomes real when the product needs to run in a customer's existing Zoom, Teams, or Meet call, or when Mosaïque needs to speak.

### The underlying variable

Direct browser capture re-captures the meeting **acoustically at each endpoint**, from a loudspeaker, after the conferencing platform has already mixed away the per-participant separation. Three consequences follow from that one property:

- every participant must run Mosaïque, because re-capture works only at an endpoint;
- browser echo cancellation has no reference signal when the call runs in a different application;
- a loudspeaker emits a mix, and a microphone cannot un-mix it.

For the prototype these are acceptable operating conditions — participants are known, consenting, and can wear headphones. For a product sold to firms whose meetings include clients, they are limits worth understanding early. That is why this analysis exists, and also why it does not need acting on yet.

---

## 2. The option space

| | Model | Who owns the media plane | How Mosaïque gets audio |
|---|---|---|---|
| **M1** | Direct capture (the prototype's ingress) | The external platform, if any | Each participant's browser microphone |
| **M2a** | Platform bot participant | The external platform | A bot joins and subscribes to per-participant tracks |
| **M2b** | Platform stream, botless | The external platform | The platform pushes per-participant streams server-to-server |
| **M3** | Native room | **Mosaïque**, via an SFU | Mosaïque hosts the meeting; the agent is a participant |
| *M4* | *OS-level desktop capture* | *The external platform* | *System audio plus microphone — one mixed stream* |

M2b was not in the original framing and is real: Zoom's Realtime Media Streams reached general availability, delivering per-participant audio, video, transcripts and participant events over WebSocket with no automated client in the meeting.

M4 is noted and set aside: one mixed stream is PRD Stage 5 diarization, with worse attribution than M1 and none of its simplicity.

---

## 3. Comparison

Relative to this product's requirements, not absolute. Verified 2026-09-03; see §7.

| Axis | M1 Direct capture | M2a Bot participant | M2b Botless stream | M3 Native room |
|---|---|---|---|---|
| **Product experience / pilotability** | Friction lands on the guest, who has no relationship with Mosaïque. Fine for internal and consenting-participant use; hard for client meetings. | Host connects once; guests do nothing. A visible bot is a familiar convention. | Smoothest UX, narrowest reach — requires the customer on Zoom with an authorizing account and entitlement. | Requires displacing the incumbent tool. Plausible for internal recurring meetings, hard for external ones. |
| **Speaker attribution** | Good with headphones; degrades with speakerphone. One participant on speakers pollutes the shared transcript. | True per-participant streams. Documented caps of roughly 16 for Zoom, 9 for Teams, 16 for Meet via an aggregator. | Per-packet `user_id` and `user_name` from Zoom; a merged stream also available. | Perfect — one track per participant, identity from the SFU. |
| **AEC / mixed audio** | The known weakness of endpoint re-capture. | Absent — tracks are pre-mix. | Absent. | Absent. An SFU never returns a participant its own track, so even a speaking agent has no echo path. |
| **Realtime latency** | Lowest transport: one hop, ~20–60 ms. | Adds a hop, jitter buffer and Opus decode, roughly +100–300 ms. | Zoom-side batching configurable from 20 ms — an explicit latency/efficiency knob. | ~30–80 ms with a colocated agent. |
| **Implementation complexity** | Lowest; already specified and in the plan. | Highest if built per platform. Teams application-hosted media requires C# on .NET Framework, Windows Server, in Azure, is developer preview, and needs `Calls.AccessMedia.All`. Meet requires a custom WebRTC client. Via an aggregator, low. | Medium, single platform: marketplace app, scopes, account credits. | Medium-high: SFU operations or managed cloud, TURN, client SDK, agent workers. |
| **Coupling to LiveKit / WebRTC** | None. | None via aggregator or SDK; direct Meet integration means writing a WebRTC client. | None — plain WebSocket. | Total. |
| **Future voice participation** | Not possible: no path into the call's audio. | Possible where outbound audio is allowed — Teams application-hosted media bots can send audio frames in real time. | Not possible: no presence to speak from. | Native and unrestricted. |
| **External meetings** | Any platform in principle, if everyone runs it. | What it exists for. | Zoom only. | None — a native room does not get Mosaïque into a customer's Zoom call. |
| **Privacy / consent** | Weakest: a participant's microphone captures people who never consented to Mosaïque, with no indicator. Constrains who the prototype may be used with. | Strongest: visible in the roster, platform recording notices, auditable. | Middle: no visible participant, but authorization is mediated by host and admin controls. | Mosaïque controls consent fully, and becomes controller or processor for all meeting media. |
| **Infrastructure** | None beyond the app. | Self-built: a container per concurrent meeting. Via aggregator: a per-bot-hour fee. | Cheapest platform path — WebSocket receivers only. | SFU, TURN, agent workers. |

### GPU is not a discriminator

Inference load is identical across all four models: N participant streams into the recognizer. Kyutai publish roughly 400 real-time streams on an H100 — at four participants per meeting, on the order of 100 concurrent meetings on one card. The infrastructure difference between these models is bot containers and SFU operations, not GPU.

### One finding that would touch any future platform ingress

Platform ingress paths deliver **16 kHz mono PCM**; Kyutai's Mimi codec is **24 kHz**. Any platform ingress therefore feeds band-limited audio into a full-band model. The WER penalty is unmeasured. **This does not affect the prototype**, which captures at 24 kHz in the browser, but it must be measured before any platform ingress is committed to — and if the penalty is large, it is an argument about the recognizer, not only the ingress.

---

## 4. Hypotheses, not recommendations

Each of the following is an unvalidated product hypothesis. Stated as hypotheses deliberately: none has been tested with a customer, and none should be treated as decided.

| # | Hypothesis | What would validate it | What would falsify it |
|---|---|---|---|
| **H-1** | Target customers will accept a bot joining their existing calls, and this is the lowest-friction route to real meetings | Prospects say they would invite a notetaker bot; competitors in the segment do this successfully | Prospects are on platforms that restrict bots, or object to a visible recorder in client meetings |
| **H-2** | Mosaïque's differentiation (French, then Darija, speaker-aware structure) survives as a bot, competing with established notetakers | French/Darija transcription quality is a decisive purchase reason on its own | Buyers treat transcription as commodity and choose on integrations |
| **H-3** | Owning the media plane (M3) is required for the PRD §23 multilingual vision — per-listener rendered audio cannot be done through any bot API | The multilingual live-translation use case is what customers actually want to buy | The thesis is PRD §24 meeting memory, in which case M3 is never needed |
| **H-4** | Someone would hold a meeting in a Mosaïque room rather than Teams or Meet | Five target customers say what it would take, and it is buildable | Nobody will switch, at which point M3 serves internal use only |

**H-3 and H-4 together are the real fork.** If the product thesis is reliable conversational memory, a platform ingress is sufficient indefinitely. If it is a multilingual meeting layer where each participant hears the others in their own language, then owning the media plane is eventually necessary, because no bot API renders distinct audio per listener. This does not need deciding now. It needs deciding before anyone builds an SFU.

---

## 5. Trigger conditions — when this document becomes relevant

This analysis should be reopened when, and not before, one of these is true:

1. The prototype has proven the core loop end to end and a real customer meeting is the next milestone.
2. A pilot customer states they will not ask their participants to run Mosaïque.
3. The product requires Mosaïque to speak in a meeting.
4. The multilingual live-translation direction (PRD §23) is confirmed as the thesis.

Until then the prototype's browser ingress is the correct ingress, because it is the only one that requires no vendor, no marketplace approval, no platform review, and no cost, and because it is deterministic and replayable in a way platform ingress is not.

---

## 6. Risks to test before committing to any of this

These are future gates. **None blocks the prototype.**

| # | Risk | Test | Required before |
|---|---|---|---|
| N-1 | 16 kHz platform audio upsampled to 24 kHz degrades Kyutai WER | Same French fixture at native 24 kHz vs 16 kHz upsampled; compare WER | Any platform ingress |
| N-2 | The chosen platform does not deliver what is assumed: Meet gives three rotating virtual audio streams, receive-only; Teams needs C#/.NET on Windows in Azure and is developer preview; Zoom RTMS has no presence | Per-platform capability audit | Choosing a platform |
| N-3 | Approval and terms-of-service risk on recording bots | Marketplace review timelines, platform terms | Pilot scheduling |
| N-4 | A vendor in the media path is reachable under non-EU jurisdiction regardless of region selection | Legal review with Q2 | Any customer data |
| N-5 | Cost per meeting-hour at real volume | Aggregator hours vs self-hosted containers vs platform credits | A pricing model |
| N-6 | LiveKit operational burden: SFU, TURN, scaling, per-participant Opus decode, agent framework maturity | Technical evaluation | Any LiveKit commitment |
| N-7 | Nobody wants a Mosaïque-hosted room | Five customer conversations (H-4) | Any LiveKit commitment |

Ordering, if this is ever picked up: **N-7 before N-6.** Do not evaluate an SFU before confirming anyone would use the room.

---

## 7. Sources

Verified 2026-09-03. Capabilities in this area change quickly; re-verify before relying on any of it.

- Zoom Realtime Media Streams — overview, media handling, per-participant audio format: `developers.zoom.us/docs/rtms/`
- Zoom on bots versus streams: `developers.zoom.us/blog/zoom-recall-ai-partnership/`
- Microsoft Teams real-time media platform and application-hosted media requirements: `learn.microsoft.com/microsoftteams/platform/bots/calls-and-meetings/`
- Google Meet Media API — concepts, virtual streams and CSRC, developer-preview enrollment: `developers.google.com/workspace/meet/media-api/`
- Aggregator per-participant audio and platform caps: `docs.recall.ai/`
- LiveKit Agents and self-hosted deployment: `docs.livekit.io/agents/`
- Kyutai STT: `kyutai.org/stt/`, `huggingface.co/kyutai/stt-1b-en_fr`, `github.com/kyutai-labs/delayed-streams-modeling`
