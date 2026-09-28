# Independent evaluation assets

These are retrospective evaluator assets, not generator inputs. The selected
17 trials cover 14 tasks. Their target-gap descriptions predate the new
generator: `dcc_pilot_handbook.md` and
`research/expanded_trials_20260926/cases.json`.

Any probes under this directory are manual controls used to check that the
published candidate still exhibits the independently identified defect. They
must never be included in `data/relational_gap_v1`, a retrieval corpus, a model
prompt, or the count of algorithm-generated successes.

The execution adapter `scripts/run_relational_gap_case.py` accepts an arbitrary
command and ordinary source test files; it contains no target-gap rules. Tests
execute against the exact task image with only the submitted candidate patch.
An assertion failure is an alarm, not automatic proof of a correctly detected
target gap. Evaluation must separately check the oracle against the issue,
the combination relation, and an applicable passing original control.

`target_census.json` freezes the seventeen target relations, source-test IDs,
observations, and previous independent evidence. `target_census.md` is the
readable table. Historical versions of temporary validation files are retained;
the most recent append fragment is not treated as the entire historical file.

The independent evaluator imports no generator or tested repository:

```bash
.venv/bin/python scripts/evaluate_relational_gap.py inventory \
  --batch-root results/relational_gap_20260928/BATCH \
  --runs results/relational_gap_20260928/runs.json \
  --output results/relational_gap_20260928/reviews.json

# Fill semantic judgments with cited, hashed evidence; unknown stays unknown.
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/BATCH \
  --reviews results/relational_gap_20260928/reviews.json \
  --output results/relational_gap_20260928/evaluation.json
```

The optional run index is a list of `{case, candidate_id, role, result,
test_ids}`. Role is `generated` or `control`; result is a file path and test IDs
identify the intended runtime leaves. A result must contain normalized
`tests:[{id,status}]`, or have adjacent JUnit XML, Vitest JSON, or Go JSON
stdout. Exit status alone does not prove that the intended test ran.

The evaluator reports retrieval hit, parent-test hit, reviewed scenario hit,
reviewed correct oracle, passing associated controls, observed generated test
failure, and reviewed target-failure cause separately. Each semantic yes/no
requires a reason plus evidence `{path,sha256}`. Preparation and execution bytes
are frozen before review and checked again during evaluation. Original control
results are reparsed, not accepted from reviewer-edited booleans.

A valid target failure through a new source parent can count as
`target_gap_detected` while missing the preselected parent-test metric. The
stricter `all_dimensions_proven` additionally requires the fixed source-parent
hit. The overall `all_17_targets_proven` is true only when all seventeen cases
have this full evidence chain. These are development-set measures; the census
does not establish generalization or zero false positives.
