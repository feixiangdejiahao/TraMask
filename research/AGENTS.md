# Research directory conventions

- Treat `research/` as an index and historical compatibility area. Put new observations and method discussions in a separate `research/<study>_<YYYYMMDD>/` directory.
- Read the relevant study's existing records before extending it. Plans and draft protocols do not establish completed experiments or accepted methods.
- Preserve frozen record contents. The authorized 2026-10-20 migration changed physical paths; resolve archived addresses through `results/path_map.json` or `scripts/result_paths.py`. Put scientific revisions in new records and link back to their sources.
- Keep execution artifacts in `results/<topic>/<run>/`. The matching `experiments/<topic>/results/` is a link to that location. Follow `experiments/NAMING.md` for names and register primary pilots in `experiments/pilot_catalog.json`.
- Use `prototypes/` for historical prototype code (formerly `experimental/`). New algorithm code belongs in `src/`.
- Use `experiments/pilots/` to locate current evaluations and per-task artifacts. Its links are reading aliases, not independent copies or new experiment runs.
- Directory organization does not validate historical scientific claims. Do not automatically promote old labels or summaries into checked evidence.
