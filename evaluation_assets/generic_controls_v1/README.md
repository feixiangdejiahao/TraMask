# Frozen generic control evaluator assets

Evaluator-only. Do not read or use this directory for generation, model prompts, rule design, candidate admission, or selection.

The original seal, input manifest, finite oracle table, correct replacements, historical indexes, builder, validator, and validation results are copied byte-for-byte. Historical absolute paths are intentionally retained in those originals. `portable_registry.json` separately resolves `inputs/<case>` and `correct/<case>` relative to this directory. The correct tree is reconstructed from original inputs and the sealed replacement bytes and compared to the original private evaluator tree before copying.

The seal predates the generic experiment. Archival occurs after v2 batch1 candidates have been fully frozen. All 361 finite rows are unchanged; finite calibration is not a claim over arbitrary generated inputs. A reference pass is not oracle validation. Per-obligation semantic adjudication must cite these sealed assets or an independent contract deduction.

Validation without running generated tests: load `scripts/evaluate_generic_controls.py` and call `sealed_assets(Path("evaluation_assets/generic_controls_v1"))`. A later audit invocation must use the nested controls case directory as --experiment-root, an explicit adjudication file, and a fresh output filename. No credentials, pilot reference patches, holdout reference implementations, or hidden verifiers are included.
