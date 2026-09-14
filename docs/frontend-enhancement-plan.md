# Frontend enhancement plan — F1 … F5

**Status: PROPOSED. Nothing in this document is built.** Agreed with Aymen on
2026-09-14. Written against `main` at `0d23100`.

This is a **parallel track to R1–R7**. The R-series carries two-user voice, the
remote ASR runtime and Azure deployment. This series carries the interface. They
touch almost disjoint files — the one overlap is `LiveMeeting.tsx`, which R5 just
changed, so rebase before F5 and read R5's diff first.

---

## 0. Before you write any CSS

Read, in this order:

| Read | For |
|---|---|
| `CLAUDE.md` | Non-negotiables and the seven Known traps. Two of them are about the frontend and you will meet both. |
| `PROJECT_STATE.md` §12 | Where the project actually is. |
| `frontend/src/styles.css`, **the comments** | The existing design brief. It is good. Do not discard it. |
| §3 below | The test contract. Breaking it is the single easiest way to waste this session. |

**The governing instruction for this whole track:** the visual system already has
a thesis, and it is a better thesis than "add glass." Your job is to finish it and
extend it — not to replace it with something generic. Every change should be
defensible from the brief that is already in the file.

---

## 1. What exists today, measured

### The system is real

`styles.css` opens with a brief and keeps it: a mosaic is many attributed pieces
composing one whole, which is what a speaker-attributed transcript is. The palette
is zellige glaze — azure, verdigris, saffron on porcelain — chosen to bridge the
French product and its Darija roadmap. The state dot is *"a tessera, not a circle."*
The meeting list is *"rows, not cards: a list of meetings is a ledger, and rows
compare better."* `--tile: 4px` is the mosaic module.

The core palette is built properly. Measured contrast against its own backgrounds:

| Pair | Ratio |
|---|---|
| `--ink-soft` #4a5c68 on `--porcelain` | 6.07:1 |
| `--azure` #1b5e8c on `--surface` | 6.94:1 |
| rail body #9fb2bd on `--ink` | 7.49:1 |
| rail foot #7c93a1 on `--ink` | 5.12:1 |
| `.health-warning` light #8a5a00 on `--surface` | 5.93:1 |

### The system has drifted

Slices 5, 6A, 6R and R3+ added rules that stopped using it.

**Six raw radii compete with the token.** `var(--tile)` appears 10 times; beside it
sit `8px` ×3, `1px` ×3, `999px` ×2, `6px` ×2, `3px` ×2 and one literal `4px`.

**A second blue that is not the brand blue.** Citations, cited segments and search
marks use `rgba(120, 160, 255, …)` at three opacities. `--azure` is `#1b5e8c`. The
citation highlight — the most product-specific affordance on the review page — is
painted in a colour the brand does not contain.

**Four status hexes with no token**: `#b3261e` ×2, `#8a5a00` ×3, `#f2b8b5` ×2,
`#f0c26b` ×2, plus six one-off `rgba()` washes and two neutral greys
`rgba(128,128,128,…)` standing in for `--grout`.

### There is a live contrast bug

**Three `@media (prefers-color-scheme: dark)` blocks exist and there is no dark
theme.** No token is ever redefined for dark; `body` stays `--porcelain` with
`--ink` text. On a machine set to dark mode the page stays light while
`.health-banner`, `.outputs-stale` and `.field-note` flip to their dark-mode
colours:

| Element in dark mode | Ratio |
|---|---|
| `.health-warning` #f0c26b on the light card | **1.66:1** |
| `.health-blocked` #f2b8b5 on the light card | **1.71:1** |

That is effectively invisible, and it is on the component whose entire job is
telling you a dependency is down — the same family as **L-35**, where the readiness
verdict was computed correctly and nothing acted on it. Fix this in F1.

### The typography has never been tested

`e2e/launch.ts:32` aborts every request to `fonts.googleapis.com` and
`fonts.gstatic.com` in all 20 browser specs. So the shipped typography — Bricolage
Grotesque and IBM Plex Sans — **has never been rendered by a single test**. Every
screenshot and every layout assertion in the suite runs on fallback system fonts.

---

## 2. The design position

### Glass, and why it is not decoration here

Glass over a flat porcelain background is a different flat colour that costs GPU
time. It earns its place only if the app gains a **ground** for it to sit on and
partially reveal.

The justification is already in the brief. **Zellige is glazed ceramic.** Glaze is a
translucent vitreous layer over a coloured body — depth by translucency, not by
drop shadow. The material was named in the first line of the stylesheet; F2 builds
what it implied. That is the difference between an extension and a trend.

### Where glass goes, and where it must never go

**Glass is for chrome:** the rail, the health banner, the status bar, the participant
roster, the segment editor, notices, and the join card.

**Glass is never for the reading surface:** `.transcript`, `.para`, `.seg`, the
ledger rows, and the body of `.outputs`. Long-form French text over a blurred,
varying backdrop is exactly where glassmorphism fails, and that text is the
product. F2 ships a Playwright assertion that the transcript's computed background
stays fully opaque, so this cannot erode later.

### Minimalism here means subtraction

The interface is already close to minimal. The work is removing what drifted in —
six radii down to four with stated roles, two blues down to one, four orphan hexes
into named tokens — not adding a visual layer on top of the mess.

---

## 3. The contract you must not break

**23 CSS class names and the French accessible names are a test contract** across
7 spec files and 20 tests. Style them; do not rename them.

```
.evidence-link  .evidence-link:not([disabled])  .health-banner  .health-detail
.line-final  .line-interim  .notice  .notice a  .outputs-provenance  .para-time
.roster  .roster-entry  .seg  .seg-editor  .speaker  .tag-interim
.transcript .line-final   .transcript .para   .transcript .seg
.transcript .seg-cited    .transcript mark    #creation-blocked
```

Accessible names the specs match on: `Nouvelle réunion`, `Rejoindre`,
`Terminer la réunion`, `Couper le micro`, `Réactiver le micro`, `Quitter`,
`Corriger`, `Enregistrer`, `Annuler`, `Régénérer`, `Détail technique`,
`Compte rendu`, `Résumé`, `Décisions`.

**Rule:** if a PR changes any French label, it updates that spec in the same
commit. Never adjust a selector to match a rename you made for style reasons —
that is how a contract silently becomes decoration.

---

## 4. The five PRs

One PR per step, documented, reviewed and merged before the next — the project's
standing working agreement. Every PR runs `npm run typecheck && npm test &&
npm run build` plus all 20 Playwright specs.

### F1 · Foundation: tokens, fonts, and the contrast bug

**Why first:** everything after this consumes the tokens. Decorating before
re-anchoring means doing it twice.

**Do:**

1. **Complete the radii scale** and migrate all six raw values onto it:
   ```css
   --tile: 4px;        /* the mosaic module — panels, inputs, buttons */
   --tile-chip: 1px;   /* tessera, meter, inline metadata — a tile, not a pill */
   --tile-panel: 8px;  /* banners, editors, glass surfaces */
   --tile-pill: 999px; /* status tags only: .tag-interim, .evidence-link */
   ```
   `--tile-chip: 1px` is deliberate, not drift — the tessera comment says so. Keep
   it and name it.

2. **Name the status colours**, replacing all four hexes and six washes:
   ```css
   --danger: #b3261e;  --danger-wash: rgba(179, 38, 30, 0.08);
   --warn:   #8a5a00;  --warn-wash:   rgba(138, 90, 0, 0.09);
   ```
   Both light values already measure 5.9:1 — keep them, just stop repeating them.

3. **Retire the second blue.** Derive the citation and search washes from `--azure`:
   ```css
   --cite-wash:        rgba(27, 94, 140, 0.14);  /* .seg-cited, .transcript mark */
   --cite-wash-strong: rgba(27, 94, 140, 0.24);  /* active citation */
   ```
   Verified: `--ink` on these over `--surface` measures 13.23:1 and 11.25:1.

4. **Delete the three `prefers-color-scheme: dark` blocks.** They are the 1.66:1 bug
   and they are the only dark rules in the file. Removing them makes the light
   theme correct and honest. A real dark theme becomes a contained later change
   because steps 1–3 will have tokenised everything it needs.

5. **Self-host the fonts.** Subset Bricolage Grotesque (variable) and IBM Plex Sans
   (400/500/600) to `latin` + `latin-ext`, serve from `frontend/public/fonts/`,
   `font-display: swap`, `<link rel="preload">` the two faces used above the fold.
   Then delete the `preconnect` and stylesheet links from `index.html` **and delete
   `isolateFromCdns` from `e2e/launch.ts` and its call sites** — it exists only to
   block those requests.

6. **Add `frontend/scripts/check-contrast.mjs`**: parse the token block, composite
   every foreground/background pair the system actually uses, fail below 4.5:1 for
   body text and 3:1 for large text and UI borders. Wire it into `npm test`.

**Exit gate:** no raw radius, status hex or non-`--azure` blue remains outside the
token block; `grep -c "prefers-color-scheme" src/styles.css` returns 0; no request
to any `fonts.google*` origin in a fresh page load; the contrast script passes and
fails when a token is deliberately broken; 20 specs green *with real fonts for the
first time*.

**Why self-hosting is the right call** — the decision was left to me, so here is the
reasoning to keep or overturn:

- **Critical path.** The CDN costs a DNS + TLS handshake to `fonts.googleapis.com`,
  and the CSS that returns then triggers a *second* connection to
  `fonts.gstatic.com`. Two extra round trips before text can paint in its real
  face. Same-origin `woff2` with `preload` costs zero extra connections.
- **The shared-cache argument is dead.** Every major browser has partitioned the
  HTTP cache by top-level site since ~2020. A visitor who loaded these fonts on
  another site does not have them for yours. The historic reason to use the CDN no
  longer holds.
- **It makes the tests honest.** The suite currently blocks the fonts, so the
  typography ships untested. Self-hosting removes the reason for the block.
- **It happens to align with Q2.** A third-party US request on every page load sits
  inside the residency question this project has open. That is a bonus, not the
  driver — the performance case stands on its own.

Cost: two subset `woff2` files, roughly 30–60 KB total, and about an hour.

### F2 · Glass on chrome

**Do:**

1. Introduce the **ground** — a low-contrast zellige-derived field behind the app
   (a tessellated pattern at very low alpha, or a soft two-stop field in azure and
   verdigris). It must stay quiet: the transcript sits on top of it and nothing may
   compete with running text.
2. Glass tokens, with a real fallback:
   ```css
   --glass-bg: rgba(255, 255, 255, 0.62);
   --glass-edge: rgba(255, 255, 255, 0.55);
   --glass-blur: 14px;
   ```
   ```css
   .glass { background: var(--surface); }           /* fallback first */
   @supports (backdrop-filter: blur(1px)) {
     .glass { background: var(--glass-bg); backdrop-filter: blur(var(--glass-blur)) saturate(1.2); }
   }
   @media (prefers-reduced-transparency: reduce) {
     .glass { background: var(--surface); backdrop-filter: none; }
   }
   ```
3. Apply to chrome only: `.rail`, `.health-banner`, `.statusbar`, `.roster-entry`,
   `.seg-editor`, `.notice`, and the join card. **Not** to `.transcript`, `.para`,
   `.seg`, `.ledger`, `.row`, or the `.outputs` body.
4. Re-run the contrast script against the **worst-case** backdrop — the darkest
   point of the ground, not the average. A translucent surface has a contrast range,
   not a contrast value.

**Exit gate:** a new spec asserts `getComputedStyle(transcript).backgroundColor` is
fully opaque and `backdropFilter` is `none`; the app is legible with
`backdrop-filter` unsupported and with reduced transparency forced; contrast passes
at worst case; 20 specs green.

### F3 · Join

**Why:** today a stranger opens an invite link and sees "Rejoindre la réunion", a
consent block, and a name field. No meeting title, no host, no sense of who else is
there — then one click takes them straight to live capture with no microphone check.

**Do:**

1. Show **what they are joining**: meeting title, host display name, who is already
   present. `GET /meetings/{id}` already carries what is needed for the first two.
2. Add a **microphone check before commit** — device picker plus the existing level
   meter — so the first time someone learns their input is wrong is not mid-sentence.
   Reuse `audio/capture.ts`; do not write a second capture path.
3. **Promote the headphone guidance.** It is currently the second paragraph of a
   consent block, styled as fine print. Without headphones one microphone hears the
   other speaker and the transcript misattributes them (L-2, A-1) — it is an
   attribution-correctness requirement, not advice. Give it its own standing.
4. Keep the join card on the ground, in glass.

**Non-negotiable:** consent stays **before** the microphone prompt — tech spec §13.3.
The mic check is part of the consented step, never before it.

**Exit gate:** a spec covers joining with a denied microphone permission and
recovering; the title and host render from the API, not from props invented on the
client; consent still precedes `getUserMedia`; 20 + new specs green.

### F4 · Dashboard

**Why:** two real defects.

- **The invite link is lost.** It appears once in a transient `.notice` after
  creation and is gone on reload, with no copy button — only a raw `<a>` with
  `word-break: break-all`. For a product whose core act is sending one person a
  link, this is the most important missing affordance in the app.
- **Rows lie about what they do.** Every row is `role="button" tabIndex={0}`, but
  `onClick` fires only when `state === "COMPLETED"`. A keyboard user tabs through
  every meeting, each announced as a button, and Enter does nothing on most of
  them. Meanwhile `.row-clickable { cursor: default }` tells a mouse user the
  opposite. Two signals, disagreeing, neither true.

**Do:**

1. Make the invite **retrievable and copyable** for any `JOINABLE` meeting — a copy
   button with a confirmation state, not a bare link.
2. Add **re-entry** into a meeting you are part of, so a host who navigates away is
   not locked out of their own live meeting.
3. **Honest affordances:** only interactive rows get `role="button"`, `tabIndex`
   and a pointer cursor. Non-interactive rows are plain content.
4. Restyle the ledger on the ground, keeping rows as rows. Do not turn the ledger
   into cards — the comment explaining why rows compare better is correct.

**Exit gate:** a spec copies an invite for an existing meeting after a reload; a
spec asserts non-completed rows expose no button role; 20 + new specs green.

### F5 · Live call

**Why:** `Terminer la réunion` is `.btn-quiet` — visually identical to
`Couper le micro`. The irreversible action that ends the meeting for everyone looks
exactly like the reversible one that mutes you. And voice, transcription and
recording are three independent states rendered as one undifferentiated status line,
after R3 made a point of keeping them honest server-side.

**Rebase on R5 first and read its diff** — it changed this file.

**Do:**

1. Real button hierarchy: destructive-primary for end, quiet for mute and leave,
   with a confirmation step on end.
2. Render **voice / transcription / recording as three distinct states**. R3 made
   the backend truthful about this (`stream.status`, `AUDIO_RECORDING_FAILED`,
   the `unavailable` copy that no longer promises recording); the UI should stop
   flattening it.
3. Let the transcript hold the visual focus — chrome in glass, recedes; transcript
   opaque, dominant.

**Exit gate:** a spec asserts end requires confirmation; a spec asserts the three
states render independently when the server reports them independently; 20 + new
specs green.

---

## 5. Non-goals — do not do these

- **No CSS framework, no Tailwind, no component library.** 758 lines of CSS with the
  reasoning written into the comments is an asset. Replacing it discards the brief.
- **No dark theme.** F1 tokenises for it; building it is a separate decision.
- **No glass on any text-reading surface.** F2 ships a test to keep it that way.
- **No animation that does not communicate a state change.**
- **No backend, API, schema or OpenAPI changes.** If a screen seems to need new
  data, say so and stop — that is a different slice.
- **No renaming of the §3 contract classes.**
- **Do not reopen L-28, Q2's residency half, or L-33.**

---

## 6. Open questions for Aymen

1. **The rail.** It is a fixed 232 px dark column carrying a wordmark, one sentence
   and "Prototype · Tranche 1", and it collapses to a bar on mobile with everything
   but the wordmark hidden. That is roughly a quarter of the horizontal space
   carrying almost no information — and `.main` then caps at 900 px, so on a wide
   screen the content sits left of centre with a large empty margin. Worth
   rethinking, but it changes every screen, so it is a question rather than a task.
2. **"Changer de jeton"** is the only authentication affordance in the app and it is
   a tiny button in the rail foot with inline `style={{…}}`, bypassing the design
   system entirely. Leave it until Slice 7 replaces token-paste with magic links
   (L-11), or give it a real home now?

---

## 7. Evidence appendix

Everything asserted above was measured on `main` at `0d23100` on 2026-09-14, in a
Linux sandbox, by reading the source and computing WCAG contrast ratios directly.
No browser screenshot was taken and no visual regression baseline exists — **there
is no CI in this repository (L-18)**, so every gate in this plan is run by hand.

What this plan does **not** claim: that any of it has been built, that the ground
and glass look good (nobody has seen them), or that the five PRs are correctly
sized. The measurements are facts; the design is a proposal.
