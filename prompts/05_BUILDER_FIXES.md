# Prompt 05 — Builder: address independent review findings

You are the **Builder** continuing an already reviewed Mosaïque milestone. The Reviewer identified problems. Read `AGENTS.md`, the relevant acceptance IDs, the current diff and this exact reviewer report:

`[PASTE REVIEW REPORT HERE OR PROVIDE PATH TO docs/reviews/Mx-review-N.md]`

Resolve verified P0/P1 issues before nonblocking concerns. For each finding:
- Reproduce or prove/disprove it; do not automatically accept inaccurate advice.
- Correct the smallest relevant part without broadening milestone scope.
- Add a regression test that fails before and passes after the fix when feasible.
- Preserve secure authorization, participant state isolation and the existing working baseline.
- Explain any finding you contest with concrete code/test evidence.

Run the applicable checks again **after the final edit**, update the acceptance/evidence report and commit a new reviewable SHA. Produce a table mapping each reviewer finding to its status, modified files, verifying tests and remaining limitations.

Do not merge or deploy. Return the new commit SHA for independent re-review.
