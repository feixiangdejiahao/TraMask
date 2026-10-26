"""Preserve reusable replay and evaluation code with byte-verifiable manifests."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tramask_pilot.corpus import receipt
from tramask_rerun.study import RUN, now, write_new


USAGE = '''TraMask replay/evidence code snapshot, 2026-10-23

Scope
This archive preserves the replay code requested for later experiments. It is
code and tests, not a substitute for the input corpus or Docker image layers.
The earlier submission_state_20261023_v01 archive is preserved separately.

Restoring the package
Use Python 3.12 and the repository dependency lock. Put src on PYTHONPATH.
The archived .py files contain no environment credentials. Original raw inputs
(instruction.md, task.toml, trajectory.json, model.patch), their receipt files,
and subject Docker images are still required. Paths in existing evidence are
absolute; copying a report elsewhere does not regenerate or re-attest inputs.

Reusing an existing final filesystem state
Use tramask_rerun.reserved.load_cases(run_directory), which follows each case's
active_submission_state.json. Do not rely on a superseded replay summary or a
registry image tag when an immutable checkpoint image_id is available.
tramask_rerun.runtime.export_checkpoint_files(checkpoint, new_output, paths)
reads explicitly requested public paths in a fresh clone. It does not run a
subject test or contact a model. Every output directory must be new.

Running a validation variant
tramask_rerun.runtime.execute_variant(checkpoint, new_output, command, timeout,
    files=..., build_commands=..., production_paths=..., generated_runtime=...)
starts a fresh container. Existing-file edits bind the predecessor SHA256;
new files require explicit new_file=True. Keep the exact working directory and
test command. Compile changed generated artifacts before testing. Interpret
actual assertions and observations; shell zero alone is not a passing test.
The validation_material and track_b_targets modules reconstruct explicit test
versions and preserve exact model proposals. They do not repair proposal bugs.

Replaying a new trial from the initial image
tramask_rerun.replay_v02.replay_case(case, raw_input_directory, new_attempt)
replays observed executed trajectory actions through the submission boundary.
It does not call a model. case must identify id/image/base_commit consistent
with task.toml. Completed attempts are only reused after receipt verification;
partial attempts are retained and are not silently restarted. Inspect every
state-validation, process-state, timeout and dependency finding before use.

Historical case-specific qualifications
The original submission_replay/submission_state code and version archives are
also included. F004's CPU build adjustment, F027's process-ID binding, S026's
background completion, HF001's explicitly unexecuted compound submission call,
and HS005's initialized-submodule read-only validation remain documented in
their original result directories. Do not generalize these exceptions to new
cases or treat a later qualification as erasing an earlier failed attempt.

Limits of a checkpoint
Docker commit preserves the filesystem, not live process memory. Recorded
tracked/index/worktree state and explicitly qualified submodule files can be
attested. The corpus lacks a complete historical untracked-byte manifest;
current filesystem inventories are preserved without claiming that missing
historical authority exists. Separate historical test-version experiments
must not overwrite the delivered production snapshot.

Local verification (no provider or Docker subject calls)
PYTHONPATH=src .venv/bin/python -m pytest tests/tramask_rerun -q
The code_manifest.json binds every archived source/test/dependency document.
Check hashes before use. Do not edit frozen run modules in place; create a new
version and record an amendment. Provider generation remains a separate,
budget-controlled action and is not implied by replay or evidence inspection.
'''


if __name__ == '__main__':
    out = ROOT / 'experiments/behavioral_masking/replay_code/evidence_state_20261023_v02'
    if out.exists():
        raise FileExistsError(out)
    old = ROOT / 'experiments/behavioral_masking/replay_code/submission_state_20261023_v01/replay_code.tar.gz'
    prior = receipt(old)
    assert prior['sha256'] == 'de51f08012168cec9c002792735eda6533a7b88243f89b68b827d60bdd5a948a'
    files = {}
    for directory in ['src/tramask_pilot', 'src/tramask_rerun', 'tests/tramask_pilot', 'tests/tramask_rerun']:
        for p in sorted((ROOT / directory).glob('*.py')):
            files[str(p.relative_to(ROOT))] = p.read_bytes()
    for p in sorted((ROOT / 'scripts').glob('*tramask*.py')):
        files[str(p.relative_to(ROOT))] = p.read_bytes()
    for name in ['requirements.txt', 'requirements.lock.txt', 'pytest.ini']:
        files[name] = (ROOT / name).read_bytes()
    files['USAGE.txt'] = USAGE.encode()
    manifest = {'created_at': now(), 'kind': 'code_only_no_credentials_corpus_or_image_layers',
        'previous_archive_preserved': prior, 'files': [
            {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name,data in sorted(files.items())]}
    files['code_manifest.json'] = (json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode()
    out.mkdir(parents=True)
    (out / 'USAGE.txt').write_bytes(files['USAGE.txt'])
    (out / 'code_manifest.json').write_bytes(files['code_manifest.json'])
    archive = out / 'replay_and_evidence_code.tar.gz'
    with archive.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w') as tar:
            for name,data in sorted(files.items()):
                item = tarfile.TarInfo(name); item.size = len(data); item.mtime = 0; item.mode = 0o644
                tar.addfile(item, io.BytesIO(data))
    with tarfile.open(archive, 'r:gz') as tar:
        assert len(tar.getmembers()) == len(files)
        for name,data in files.items():
            assert tar.extractfile(name).read() == data
    assert receipt(old) == prior
    write_new(RUN / 'reusable_code_archive_v01.json', {'created_at': now(),
        'archive': receipt(archive), 'manifest': receipt(out / 'code_manifest.json'),
        'usage': receipt(out / 'USAGE.txt'), 'files': len(files), 'archive_member_bytes_verified': True,
        'previous_archive_unchanged': prior,
        'checkpoint_authority': 'Active per-case submission states and result receipts remain outside the code archive.'})
    print(json.dumps({'archive': str(archive), 'files': len(files), 'sha256': receipt(archive)['sha256']}))
