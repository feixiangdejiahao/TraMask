# Research directory conventions

- Treat `research/` as an index and historical compatibility area. Put new observations and method discussions in a separate `research/<study>_<YYYYMMDD>/` directory.
- Read the relevant study's existing records before extending it. Plans and draft protocols do not establish completed experiments or accepted methods.
- Existing historical paths, relative symlinks, file contents, and frozen records are referenced by old scripts and provenance checks. Put revisions in new records and link back to their sources.
- Keep execution artifacts in `experiments/<topic>/results/<run>/`. Follow `experiments/README.md` for new run names and register primary pilots in `experiments/pilot_catalog.json`.
- Use `experiments/pilots/` to locate current evaluations and per-task artifacts. Its links are reading aliases, not independent copies or new experiment runs.
- Directory organization does not validate historical scientific claims. Do not automatically promote old labels or summaries into checked evidence.
