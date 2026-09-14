# Self-hosted webfonts

Four files, four `@font-face` blocks at the top of `src/styles.css`. They
replaced the render-blocking Google Fonts `<link>` that used to sit in
`index.html`; the reasoning is in the stylesheet comment and in
`docs/frontend-enhancement-plan.md` §F1.

## Provenance — these are Google's own subsets, byte-for-byte

Nothing here was re-generated or re-compressed. Each file is what
`fonts.gstatic.com` serves for the `latin` / `latin-ext` unicode-ranges of the
Google Fonts CSS the app used to load, fetched on **2026-09-14**.

| File | Bytes | sha256 (first 16) |
|---|---:|---|
| `bricolage-grotesque-latin.woff2` | 76 868 | `85f55a58a31e61a2` |
| `bricolage-grotesque-latin-ext.woff2` | 30 636 | `1d04719f1325400e` |
| `ibm-plex-sans-latin.woff2` | 40 240 | `056e4e2459f57a00` |
| `ibm-plex-sans-latin-ext.woff2` | 25 868 | `ae1d854fefa1167a` |

**Both families ship as variable fonts**, which is why one file covers every
weight the interface uses — Bricolage Grotesque carries `opsz 12…96` and
`wght 200…800`, IBM Plex Sans carries `wght 100…700`. The `@font-face` blocks
declare those ranges. That is also why the total is ~174 KB rather than the
~30–60 KB the plan estimated: the estimate assumed static instances, and the
CDN was already serving these same bytes. Self-hosting removed two connections,
not weight.

Only the two `latin` files are preloaded. French lives entirely inside the
`latin` range (including `œ`), so `latin-ext` is fetched only if a glyph
outside it actually appears on the page.

## Re-fetching

The URLs are versioned by content, so a future Google Fonts release will serve
different ones. To refresh, request the CSS with a browser `User-Agent` (an
unknown UA gets `ttf` instead of `woff2`) and take the two `latin` /
`latin-ext` `src:` URLs from each family:

```sh
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 \
(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
curl -A "$UA" 'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,200..800&display=swap'
curl -A "$UA" 'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap'
```

If the `unicode-range` values in the returned CSS differ from the ones in
`src/styles.css`, update the stylesheet to match — a stale range means glyphs
silently fall back to `system-ui`.

## Licence

Both families are under the SIL Open Font License 1.1, copied here in full as
that licence requires when the font software is redistributed:

- Bricolage Grotesque — `OFL-bricolage-grotesque.txt`.
  Copyright 2022 The Bricolage Grotesque Project Authors.
- IBM Plex Sans — `OFL-ibm-plex-sans.txt`.
  Copyright © 2017 IBM Corp. with Reserved Font Name "Plex".
