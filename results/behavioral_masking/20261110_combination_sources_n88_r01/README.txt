88-trajectory audit: portable publication sources

The frozen analysis is in ../20261109_combination_alternatives_n88_r01/.
The matched public-model pilot is in ../20261109_cross_model_gap_pilot_r01/.

This directory includes all 88 original trajectories, issue descriptions,
submitted patches, task Verifier patches, original CTRF reports, and the exact
repository/log/script files quoted by the audit. Files are deduplicated by SHA256.
manifest.json maps each original location to its repository-relative source file.

cases/ contains portable copies of case.json, manual_review.json and
evaluation_failures.json. Only loader paths are changed. The original records
remain unchanged in the frozen analysis directory. Historical inventory and
prior-study paths in descriptive metadata retain their original locations;
the actually cited evidence needed by verification is bundled here.

From the repository root, using Python 3 and its standard library:

python3 scripts/publish_combination_audit.py verify --bundle results/behavioral_masking/20261110_combination_sources_n88_r01

This checks source hashes, every recorded original quote, case/full-read/ID
invariants, and equality between original CTRF failed records and the published
635-record evaluation projection. It does not execute the proposed new tests.

Reports to read first:
../20261109_combination_alternatives_n88_r01/report.txt
../20261109_combination_alternatives_n88_r01/cases_zh.txt
../20261109_cross_model_gap_pilot_r01/report.txt
