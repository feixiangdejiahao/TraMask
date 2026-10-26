# Research directory conventions

- For subsequent `se-auto-research` work on this project, use `research/workspaces/test_augmentation/` as the workspace unless the user chooses another location.
- Treat `research/` as an index and historical compatibility area. Do not initialize skill templates directly at this level.
- Use a separate `research/workspaces/<study>/` directory for another study. Each study owns its scope, ledger, and protocols.
- Read the selected workspace's `README.md` and scope before adding research records. Templates and draft protocols do not establish completed experiments or accepted methods.
- Existing historical paths, relative symlinks, file contents, and frozen records are referenced by old scripts and provenance checks. Put revisions in new records and link back to their sources.
- Keep execution artifacts in the existing `experiments/<topic>/results/<run>/` layout unless a task explicitly needs another layout. Record their locations in the workspace.
- The skill's ledger auditor resolves local evidence inside its workspace. Copy only the evidence files actually used into workspace-local `evidence/` and record their original paths and hashes. A symlink outside the workspace does not satisfy that check.
- Directory organization does not validate historical scientific claims. Do not automatically promote old labels or summaries into checked evidence.
