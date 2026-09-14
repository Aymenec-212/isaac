#!/usr/bin/env node
/**
 * Contrast gate for the Mosaïque visual system.
 *
 * Why this exists: `styles.css` had three `@media (prefers-color-scheme: dark)`
 * blocks and no dark theme, so on a machine set to dark the page stayed light
 * while the health banner flipped to its dark colours — 1.66:1, effectively
 * invisible, on the one component whose whole job is telling you a dependency
 * is down. Nothing caught it, because nothing was measuring. This measures.
 *
 * It reads the real stylesheet rather than a copy of the palette, so breaking a
 * token breaks this run. Translucent layers are composited over the opaque
 * surface they actually sit on, and `opacity` on a rule is folded in as alpha —
 * a wash at 0.08 and a foreground at 0.45 both change the answer.
 *
 * Two lists:
 *
 *   PAIRS — must hold. 4.5:1 for body text, 3:1 for large text and for the
 *           non-text things that carry meaning (WCAG 1.4.3 / 1.4.11).
 *   GAPS  — known shortfalls this pass did not have the mandate to change,
 *           each pinned to the ratio measured today. They cannot get worse
 *           without failing the build, and they are printed on every run so
 *           they stay visible instead of becoming folklore.
 *
 * Usage: node scripts/check-contrast.mjs [--verbose]
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const CSS_PATH = resolve(here, "../src/styles.css");

/* ---------- a very small CSS reader ------------------------------------- */

/**
 * Top-level rules only. Everything inside `@media`/`@supports`/`@font-face` is
 * skipped on purpose: this asks what a colour *is*, and the conditional blocks
 * in this stylesheet carry layout and motion, not colour. If that stops being
 * true, this is the thing to change first.
 */
function readRules(css) {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = new Map();
  let i = 0;
  while (i < text.length) {
    const open = text.indexOf("{", i);
    if (open === -1) break;
    const prelude = text.slice(i, open).trim();
    let depth = 1;
    let j = open + 1;
    while (j < text.length && depth > 0) {
      if (text[j] === "{") depth += 1;
      else if (text[j] === "}") depth -= 1;
      j += 1;
    }
    const body = text.slice(open + 1, j - 1);
    if (!prelude.startsWith("@")) {
      const decls = new Map();
      for (const part of body.split(";")) {
        const colon = part.indexOf(":");
        if (colon === -1) continue;
        decls.set(part.slice(0, colon).trim(), part.slice(colon + 1).trim());
      }
      for (const selector of prelude.split(",").map((s) => s.trim())) {
        const existing = rules.get(selector) ?? new Map();
        for (const [k, v] of decls) existing.set(k, v);
        rules.set(selector, existing);
      }
    }
    i = j;
  }
  return rules;
}

const RULES = readRules(readFileSync(CSS_PATH, "utf8"));

/** A custom property from `:root`, with `var()` indirection resolved. */
function token(name) {
  const root = RULES.get(":root");
  if (!root?.has(name)) throw new Error(`no ${name} in :root — did a token get renamed?`);
  return resolveVars(root.get(name));
}

function resolveVars(value) {
  let out = value;
  for (let guard = 0; guard < 8 && out.includes("var("); guard += 1) {
    out = out.replace(/var\(\s*(--[\w-]+)\s*\)/g, (_, name) => {
      const root = RULES.get(":root");
      if (!root?.has(name)) throw new Error(`no ${name} in :root — did a token get renamed?`);
      return root.get(name);
    });
  }
  return out.trim();
}

/** One declared value, e.g. decl(".rail-foot", "color"). */
function decl(selector, property) {
  const rule = RULES.get(selector);
  if (!rule?.has(property)) {
    throw new Error(`no \`${property}\` on \`${selector}\` — did a selector get renamed?`);
  }
  return resolveVars(rule.get(property));
}

/* ---------- colour ------------------------------------------------------ */

function parseColor(value) {
  const v = value.trim();
  if (v === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
  const rgba = v.match(/^rgba?\(([^)]+)\)$/i);
  if (rgba) {
    const parts = rgba[1].split(/[,/]/).map((p) => p.trim());
    const [r, g, b] = parts.slice(0, 3).map(Number);
    const a = parts.length > 3 ? Number(parts[3]) : 1;
    return { r, g, b, a };
  }
  const hex = v.match(/^#([0-9a-f]{3,8})$/i);
  if (hex) {
    let h = hex[1];
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
    const n = (at) => parseInt(h.slice(at, at + 2), 16);
    return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 };
  }
  throw new Error(`cannot parse colour: ${value}`);
}

/** Source-over, bottom layer first. The bottom layer must be opaque. */
function flatten(layers) {
  const stack = layers.map(parseColor);
  if (stack[0].a !== 1) throw new Error("the bottom layer of a stack must be opaque");
  return stack.reduce((below, above) => ({
    r: above.r * above.a + below.r * (1 - above.a),
    g: above.g * above.a + below.g * (1 - above.a),
    b: above.b * above.a + below.b * (1 - above.a),
    a: 1,
  }));
}

const channel = (c) => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};

const luminance = ({ r, g, b }) =>
  0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);

function ratio(foregroundLayers, backgroundLayers) {
  const bg = flatten(backgroundLayers);
  const fg = flatten([rgb(bg), ...foregroundLayers]);
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const rgb = ({ r, g, b }) => `rgb(${r}, ${g}, ${b})`;

/** A foreground colour at a given element `opacity`, as an rgba() string. */
function faded(color, opacity) {
  const c = parseColor(color);
  return `rgba(${c.r}, ${c.g}, ${c.b}, ${(c.a * opacity).toFixed(4)})`;
}

/* ---------- the surfaces text actually sits on -------------------------- */

const PORCELAIN = token("--porcelain"); // the page
const SURFACE = token("--surface"); //     cards: ledger, transcript, outputs…
const INK = token("--ink"); //             the rail

const BODY = 4.5; // WCAG 1.4.3, text below 18.66px/24px bold
const LARGE = 3; //  WCAG 1.4.3, large text
const UI = 3; //     WCAG 1.4.11, non-text that carries meaning

/**
 * Every pair the interface actually renders. `on` is bottom-up: the opaque
 * surface first, then any wash painted over it.
 */
const PAIRS = [
  // -- running text ------------------------------------------------------
  { what: "body text on a card", fg: [token("--ink")], on: [SURFACE], min: BODY },
  { what: "body text on the page", fg: [token("--ink")], on: [PORCELAIN], min: BODY },
  { what: ".row-meta / .para-time / .roster-tag", fg: [token("--ink-soft")], on: [SURFACE], min: BODY },
  { what: ".head p / .empty", fg: [token("--ink-soft")], on: [PORCELAIN], min: BODY },
  { what: ".speaker / .notice a / .consent-tip", fg: [decl(".speaker", "color")], on: [SURFACE], min: BODY },
  { what: ".evidence / .owner / .due chips", fg: [decl(".evidence", "color")], on: [token("--porcelain")], min: BODY },

  // -- the rail ----------------------------------------------------------
  { what: ".rail default text", fg: [decl(".rail", "color")], on: [INK], min: BODY },
  { what: ".rail p", fg: [decl(".rail p", "color")], on: [INK], min: BODY },
  { what: ".rail-foot", fg: [decl(".rail-foot", "color")], on: [INK], min: BODY },

  // -- controls ----------------------------------------------------------
  { what: ".btn-primary label", fg: [decl(".btn-primary", "color")], on: [decl(".btn-primary", "background")], min: BODY },
  { what: ".btn-primary:hover label", fg: [decl(".btn-primary", "color")], on: [decl(".btn-primary:hover:not(:disabled)", "background")], min: BODY },
  { what: ".btn-primary:disabled label", fg: [decl(".btn-primary", "color")], on: [decl(".btn-primary:disabled", "background")], min: LARGE },
  { what: ".btn-quiet label on the page", fg: [decl(".btn-quiet", "color")], on: [PORCELAIN], min: BODY },
  { what: '"Changer de jeton" at rest in the rail', fg: [decl(".rail .btn-quiet", "color")], on: [INK], min: BODY },
  { what: '"Changer de jeton" on hover', fg: [decl(".rail .btn-quiet:hover", "color")], on: [decl(".btn-quiet:hover", "background")], min: BODY },
  { what: ".btn-quiet border in the rail", fg: [decl(".btn-quiet", "border-color")], on: [INK], min: UI },

  // -- status. The reason this file exists. ------------------------------
  { what: ".health-blocked / .health-unreachable", fg: [decl(".health-blocked", "color")], on: [SURFACE, decl(".health-blocked", "background")], min: BODY },
  { what: ".health-warning", fg: [decl(".health-warning", "color")], on: [SURFACE, decl(".health-warning", "background")], min: BODY },
  { what: ".health-detail (opacity 0.85)", fg: [faded(decl(".health-blocked", "color"), Number(decl(".health-detail", "opacity")))], on: [SURFACE, decl(".health-blocked", "background")], min: BODY },
  { what: ".outputs-stale", fg: [decl(".outputs-stale", "color")], on: [SURFACE, decl(".outputs-stale", "background")], min: BODY },
  { what: ".field-note", fg: [decl(".field-note", "color")], on: [PORCELAIN], min: BODY },

  // -- citation and search, now derived from --azure ---------------------
  { what: "text under .transcript mark", fg: [token("--ink")], on: [SURFACE, decl(".transcript mark", "background")], min: BODY },
  { what: "text under .seg-cited", fg: [token("--ink")], on: [SURFACE, decl(".seg-cited", "background")], min: BODY },
  { what: "text under .seg-cited + mark", fg: [token("--ink")], on: [SURFACE, decl(".seg-cited", "background"), decl(".transcript mark", "background")], min: BODY },
  { what: ".line-interim under a mark", fg: [token("--ink-soft")], on: [SURFACE, decl(".transcript mark", "background")], min: BODY },

  // -- non-text that carries meaning (WCAG 1.4.11) -----------------------
  { what: ".tessera JOINABLE on a card", fg: [decl('.tessera[data-state="JOINABLE"]', "background")], on: [SURFACE], min: UI },
  { what: ".tessera LIVE on a card", fg: [decl('.tessera[data-state="LIVE"]', "background")], on: [SURFACE], min: UI },
  { what: ".tessera FINALIZING on a card", fg: [decl('.tessera[data-state="FINALIZING"]', "background")], on: [SURFACE], min: UI },
  { what: ".tessera default on a card", fg: [decl(".tessera", "background")], on: [SURFACE], min: UI },
  { what: ".meter-fill in its track", fg: [decl(".meter-fill", "background")], on: [decl(".meter", "background")], min: UI },
  { what: ".roster-entry[data-speaking] border", fg: [decl('.roster-entry[data-speaking="true"]', "border-color")], on: [PORCELAIN], min: UI },
  { what: ":focus-visible ring on the page", fg: [decl(":focus-visible", "outline").split(" ").pop()], on: [PORCELAIN], min: UI },
  { what: ":focus-visible ring on a card", fg: [decl(":focus-visible", "outline").split(" ").pop()], on: [SURFACE], min: UI },
];

/**
 * Category accents: a coloured left edge on an element that always carries its
 * own text. WCAG 1.4.11 covers non-text content *required* to understand a
 * component or its state, and none of these is required — the notice says what
 * it is in words, an interim line is labelled `.tag-interim` in words, and a
 * paragraph's azure edge says nothing the speaker name above it does not. So
 * they get no threshold. They are measured and printed anyway, because F2
 * changes what sits behind them and this is where that will show up.
 *
 * `.notice` measures 2.98:1 on porcelain — two hundredths under the bar it is
 * exempt from. Recorded rather than rounded away: if this reading is wrong, the
 * fix is a slightly darker `--saffron`, and that is a palette decision.
 */
const ACCENTS = [
  { what: ".line-final left border", fg: [decl(".line-final", "border-left-color")], on: [SURFACE] },
  { what: ".line-interim left border", fg: [decl(".line-interim", "border-left-color")], on: [SURFACE] },
  { what: ".para left border", fg: [decl(".para", "border-left").split(" ").pop()], on: [SURFACE] },
  { what: ".notice left border", fg: [decl(".notice", "border-left").split(" ").pop()], on: [PORCELAIN] },
  { what: ".consent left border", fg: [decl(".consent", "border-left").split(" ").pop()], on: [PORCELAIN] },
  { what: ".outputs-stale left border", fg: [decl(".outputs-stale", "border-left").split(" ").pop()], on: [SURFACE, decl(".outputs-stale", "background")] },
];

/**
 * Known shortfalls. Each is pinned to the ratio measured on 2026-09-14 and
 * fails if it drops below it, so they can be paid off but not quietly eroded.
 * Moving one of these into PAIRS is the definition of having fixed it.
 */
const GAPS = [
  {
    what: ".grout hairline around inputs and cards",
    fg: [token("--grout")],
    on: [SURFACE],
    want: UI,
    floor: 1.38,
    why: "A text input's only boundary is a `--grout` hairline on `--surface`, which WCAG 1.4.11 asks to reach 3:1. Darkening `--grout` changes how every card and row looks, which is F2's mandate, not F1's re-anchoring.",
  },
  {
    what: ".seg-edit ✎ at rest (opacity 0.45)",
    fg: [faded(token("--ink-soft"), Number(decl(".seg-edit", "opacity")))],
    on: [SURFACE],
    want: UI,
    floor: 2.05,
    why: "Deliberately recessive so it does not compete with the transcript, and it reaches full `--azure` on hover and on `:focus-visible`. Raising the resting opacity is a visual decision for F2.",
  },
  {
    what: ".evidence-link at rest (opacity 0.8)",
    fg: [faded(token("--ink"), Number(decl(".evidence-link", "opacity")))],
    on: [SURFACE],
    want: BODY,
    floor: 8.6,
    why: "Passes as text; listed because the same `opacity` trick is what sinks `.seg-edit`, and the disabled variant drops to 0.4. Disabled controls are exempt from 1.4.3, but a reader still has to tell a real citation from one with no audio behind it.",
  },
  {
    what: ":focus-visible ring in the dark rail",
    fg: [decl(":focus-visible", "outline").split(" ").pop()],
    on: [INK],
    want: UI,
    floor: 2.36,
    why: "`--azure` on `--ink` is too close to read as a focus indicator. The rail holds one focusable control — \"Changer de jeton\", whose invisible label F1 did fix — so a keyboard user can now see the button but still not see that it is focused. One line (`.rail :focus-visible { outline-color: var(--porcelain) }`, 14.33:1) whenever the rail's focus treatment is decided; F1 fixed the label because it was invisible to everyone, and left the ring because it is a visual choice.",
  },
];

/* ---------- run --------------------------------------------------------- */

const verbose = process.argv.includes("--verbose");
const fmt = (n) => `${n.toFixed(2)}:1`;
const failures = [];

console.log(`contrast · ${CSS_PATH.replace(/.*\/frontend\//, "")}\n`);

for (const pair of PAIRS) {
  const got = ratio(pair.fg, pair.on);
  const ok = got >= pair.min;
  if (!ok) failures.push(`${pair.what}: ${fmt(got)}, needs ${pair.min}:1`);
  if (!ok || verbose) {
    console.log(`  ${ok ? "ok  " : "FAIL"}  ${fmt(got).padStart(8)}  (min ${pair.min})  ${pair.what}`);
  }
}

console.log(`  ${PAIRS.length} pairs checked, ${PAIRS.length - failures.length} pass\n`);

if (verbose) {
  console.log("category accents — measured, no threshold (see the comment above ACCENTS):\n");
  for (const accent of ACCENTS) {
    console.log(`  --    ${fmt(ratio(accent.fg, accent.on)).padStart(8)}             ${accent.what}`);
  }
  console.log("");
}

if (GAPS.length) {
  console.log(`known gaps — measured, pinned, not yet fixed:\n`);
  for (const gap of GAPS) {
    const got = ratio(gap.fg, gap.on);
    const worse = got < gap.floor;
    if (worse) {
      failures.push(
        `${gap.what} got worse: ${fmt(got)}, was pinned at ${gap.floor.toFixed(2)}:1`,
      );
    }
    console.log(`  ${worse ? "WORSE" : "gap  "} ${fmt(got).padStart(8)}  (wants ${gap.want}:1)  ${gap.what}`);
    if (verbose) console.log(`         ${gap.why}\n`);
  }
  console.log(`  ${GAPS.length} gaps. Run with --verbose for why each one is still here.\n`);
}

if (failures.length) {
  console.error("contrast check failed:");
  for (const f of failures) console.error(`  · ${f}`);
  process.exit(1);
}

console.log("contrast ok");
