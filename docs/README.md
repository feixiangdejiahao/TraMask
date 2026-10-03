# Research reports

[HTML progress report](research_progress.html): method families and subversions, experiments, all 17 trials, false alarms, model cost, and next research decisions. The English report uses short sentences and includes a Chinese term guide. Open it directly in a browser. It has no external page dependencies.

## Archived presentation

[PDF](combination_testing_research.pdf) · [Beamer source](combination_testing_research.tex)

English, 27 slides, 16:9. The deck covers the problem, observation-production-path research abstraction, implemented workflow, formal definitions, HTTPX and Koota worked examples, all 17 trial results, contribution hypotheses, limitations, and future evaluation.

## Build

From the repository root:

```bash
make -C docs
```

Required TeX packages: Beamer, TikZ/PGF, FontAwesome5, Latin Modern, AMS math, booktabs, and listings. The build uses `latexmk` and `pdflatex`. All figures are native vector graphics; there are no external assets or model calls. Intermediate files go to the ignored `docs/build/` directory.

## Evidence snapshot

The completed fresh v3 experiment is frozen at `7a8ff95`: 16 confirmed defect witnesses across 17 development trials / 14 distinct tasks, with 12 retained and 4 revised oracles. It does not include a patch-repair/hidden-test loop. The later optional strict/may source-priority prototype is presented separately; its completed fixed-pool census found no exposure gain (strict unchanged; may worse). No new model or subject execution was performed in that study.

Authoritative local evidence:

- Main score: `results/relation_search_20260929_v3/evaluation/uniform_fresh_impact_v3/checkpoint_14.json`.
- HTTPX witness: `N01_c8e075c82686eb21c4222575_deliveries.json` in the same directory.
- Koota witness: `N09_08f2c625387570b30312_runtime_index.json` in the same directory.
- Generated source and native controls/failures: `results/relation_search_20260929_v3/uniform_fresh_impact_v3/N01/round_000/` and the corresponding `N09` directory.
- Current method and evaluation: `research/method_design.md`, `research/relation_search_v3_evaluation.md`, and `research/patch_observation_priority_protocol.md`.

The delivered PDF was compiled without LaTeX errors or overfull/underfull boxes, rendered and visually reviewed page by page, and checked for text extending beyond page boundaries. Code on the worked-example slides is explicitly condensed from executed witnesses; exact source remains in the experiment artifacts.
