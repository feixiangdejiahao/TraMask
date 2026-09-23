"""Byte-preserving archival of preregistered evaluator-only assets after freeze."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,shutil
ROOT=Path('/home/jhx/combination_coverage');PRIVATE=Path('/tmp/cc-generic-evaluator-v1')
OUT=ROOT/'evaluation_assets/generic_controls_v1';OUT.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
files={
 'seal.json':ROOT/'research/generic_controls_v1_seal.json',
 'source_manifest.json':ROOT/'data/generic_controls_v1/manifest.json',
 'oracle_table.json':PRIVATE/'oracle_table.json',
 'correct_replacements.json':PRIVATE/'correct_replacements.json',
 'original_correct_repositories.json':PRIVATE/'correct_repositories.json',
 'finite_validation.json':PRIVATE/'validation.json',
 'build_controls.py':PRIVATE/'build_controls.py',
 'validate_domains.py':PRIVATE/'validate_domains.py',
 'source_control_runs.json':ROOT/'results/generic_controls_v1/source_control_runs.json',
 'source_validation.json':ROOT/'research/generic_controls_v1_validation.json'}
originals={str(p):sha(p) for p in files.values()}
for name,p in files.items():shutil.copyfile(p,OUT/name)
seal=json.loads((OUT/'seal.json').read_text())
for name,key in [('source_manifest.json','manifest_sha256'),('oracle_table.json','oracle_table_sha256'),('correct_replacements.json','correct_replacements_sha256')]:
 assert sha(OUT/name)==seal[key]
manifest=json.loads((OUT/'source_manifest.json').read_text())
replacements=json.loads((OUT/'correct_replacements.json').read_text())
registry=[]
for case in manifest:
 cid=case['id'];original_repo=Path(case['repository'])
 for item in case['files']:
  rel=Path(item['path']);source=original_repo/rel;assert sha(source)==item['sha256']
  candidate=OUT/'inputs'/cid/rel;candidate.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,candidate)
  correct=OUT/'correct'/cid/rel;correct.parent.mkdir(parents=True,exist_ok=True)
  replaced=replacements.get(cid,{}).get(str(rel));expected=replaced.encode() if replaced is not None else source.read_bytes()
  sealed_correct=PRIVATE/'correct_repositories'/cid/rel;assert sealed_correct.read_bytes()==expected
  shutil.copyfile(sealed_correct,correct)
 registry.append({'id':cid,'language':case['language'],'repository':str(Path('inputs')/cid),
                  'reference_repository':str(Path('correct')/cid),'seed_command_original':case['seed_command']})
(OUT/'portable_registry.json').write_text(json.dumps({'relative_to':'archive_directory','evaluator_only':True,'cases':registry},indent=2)+'\n')
(OUT/'README.md').write_text('''# Frozen generic control evaluator assets

Evaluator-only. Do not read or use this directory for generation, model prompts, rule design, candidate admission, or selection.

The original seal, input manifest, finite oracle table, correct replacements, historical indexes, builder, validator, and validation results are copied byte-for-byte. Historical absolute paths are intentionally retained in those originals. `portable_registry.json` separately resolves `inputs/<case>` and `correct/<case>` relative to this directory. The correct tree is reconstructed from original inputs and the sealed replacement bytes and compared to the original private evaluator tree before copying.

The seal predates the generic experiment. Archival occurs after v2 batch1 candidates have been fully frozen. All 361 finite rows are unchanged; finite calibration is not a claim over arbitrary generated inputs. A reference pass is not oracle validation. Per-obligation semantic adjudication must cite these sealed assets or an independent contract deduction.

Validation without running generated tests: load `scripts/evaluate_generic_controls.py` and call `sealed_assets(Path("evaluation_assets/generic_controls_v1"))`. A later audit invocation must use the nested controls case directory as --experiment-root, an explicit adjudication file, and a fresh output filename. No credentials, pilot reference patches, holdout reference implementations, or hidden verifiers are included.
''')
shutil.copyfile(__file__,OUT/'archive_assets.py')
assert originals=={str(p):sha(p) for p in files.values()}
inventory={'created_at':datetime.now(timezone.utc).isoformat(),'original_bytes_preserved':True,
           'source_files_sha256':originals,'evaluator_only':True,
           'v2_frozen_before_archival_ledger_sha256':sha(ROOT/'results/generic_v2/batch1/direct_and_empty_admission_ledger.json'),
           'files':{str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file()}}
(OUT/'archive_inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
print('Archived',len(inventory['files']),'files; original byte checks passed:',OUT)
