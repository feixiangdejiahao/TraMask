# 211-trial standalone bilingual HTML

Open [the report](../../../docs/deepswe_failure_manual_20261006.html). Its styles, scripts, task requirements, patches and selected evaluation/validation evidence are embedded, so it works as a single file offline. Every trial includes an adaptive combination table and a test-generation timeline with recorded text, actions and feedback. Evidence is stored in independently compressed chunks, decoded per trial, timeline or complete source on demand.

- `manifest.json`: build scope, source groups and HTML checksum.
- `audit.json`: complete embedded source checks, bilingual coverage, unchanged judgments/scores, all 211 authored tables, exact trajectory quote offsets, source traceability and portable reading-copy consistency.
- `browser_checks.json`: actual Chromium checks for offline use, both languages, filters, deep links, all 211 lazy-rendered cases and tables, step selection, deferred timelines/actions, exact patch downloads and responsive layout.
- `desktop-*.png` / `mobile-*.png`: browser screenshots in both languages.
- `startup_baseline.json` / `startup_optimized.json`: eight independent offline startup samples per version, with normal and throttled CPU. Controls readiness and first-trial DOM availability are distinct from first paint. Full methods and per-run results are recorded in each file.
- `startup_visuals.json`: eight startup samples of the current HTML including combination tables and independently deferred timelines. Each run records the HTML checksum, readiness, paint and decoding counters. The two earlier files describe earlier HTML versions.

These checks validate the report, not a coding-agent repair experiment. The report retains the existing 88 supported and 30 conditional judgments; no F2P/P2P improvement was measured.
