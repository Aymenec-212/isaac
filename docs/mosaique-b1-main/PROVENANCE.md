# Restored regression data — M0-R1

Restored byte-for-byte from repository main
`6e9e85bd3806cf7f5c0205ece97e285f8d62da9e`, not from a local external project:

| File | Main Git blob |
|---|---|
| b1-report.json | 9f9e28039edc25cf2130ffaba4e318ab06baacc3 |
| b1-tokens.jsonl | 88d887409046f84a005f241e558b2a929551b02e |
| ../slice4-last-test-report.json | efdfc1012ad1462247d50190a31111fcbf92b216 |

History: B1 artifacts entered in `07dbfa9` (B1 report); Slice 4 report in `81a6cba`
(Slice 4 verification test suite). Main's `docs/spikes/B1-findings.md` identifies
the 2026-09-08 B1 run by Aymen on Apple M1, one 64-second first-person French
developer fixture; main's `PROJECT_STATE.md` records the later 116-second prepared
French monologue on the developer's machine. The report text was inspected: it
contains developer/demo speech, model metadata, timings and test identifiers,
not customer meeting material or credential values. The developer's name/location
already appear in the historical text; this restoration does not claim anonymization.

Only existing textual reports/token events are restored. No audio, keys, environment
files, model weights or third-party source copies are added. This preserves the
repository's own regression evidence under the user's instruction to repair the
branch; it is not a new license claim for distributing underlying recordings.

`7412d8d` deleted these files while leaving consumers unchanged. Keeping their
original bytes preserves token-piece counts, timing bursts, punctuation, orphaned
final-word evidence and prompt-budget assertions. Synthetic substitutions would
change that evidence and are unnecessary here. Historical measurements remain
historical; passing replay tests does not rerun the model or verify enterprise ASR.
