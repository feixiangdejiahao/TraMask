"""Submission equivalence is a research invariant, independent of test outcomes."""
import json
from pathlib import Path

from ..artifacts import file_ref, write_json


SCRIPT = Path(__file__).with_name('state_guest.py').read_text()


def original_gitlinks(runtime):
    process = runtime.control(['python3', '-I', '-c', SCRIPT],
                              input_bytes=b'{"operation":"gitlinks"}', timeout=180)
    return json.loads(process.stdout)


def validate_submission_state(runtime, patch, out, *, base_commit, gitlink_baseline):
    out = Path(out)
    out.mkdir(parents=True)
    remote = runtime.scratch + '/submitted.patch'
    runtime.copy_to(patch, remote)
    request = {'operation': 'compare', 'base_commit': base_commit,
               'patch': remote, 'scratch_parent': runtime.scratch}
    process = runtime.control(['python3', '-I', '-c', SCRIPT],
                              input_bytes=json.dumps(request).encode(), timeout=180)
    observation = json.loads(process.stdout)
    write_json(out / 'observation.json', observation)
    expected_links = {p: r for p, r in observation['expected'].items() if r['mode'] == '160000'}
    link_differences = [p for p, r in expected_links.items()
                        if observation['gitlinks'].get(p) != gitlink_baseline.get(p)
                        or gitlink_baseline.get(p, {}).get('oid') != r['oid']]
    commit_matches = observation['expected_tree'] == observation['head_tree']
    index_matches = observation['expected'] == observation['actual_index']
    worktree_matches = not observation['mismatches'] and not link_differences
    matched = commit_matches and index_matches and worktree_matches
    report = {'matched': matched, 'submission_state_status': 'matched' if matched else 'mismatch',
              'submitted_commit_tree_matches': commit_matches,
              'index_tree_matches_submitted_commit': index_matches,
              'working_tree_matches_submitted_commit': worktree_matches,
              'mismatches': observation['mismatches'], 'gitlink_differences': link_differences,
              'expected_tree': observation['expected_tree'], 'head_tree': observation['head_tree'],
              'base_commit': base_commit, 'runtime_initial_head': runtime.base_commit,
              'image_id': runtime.image_id, 'subject_files_or_real_index_patched': False,
              'submitted_patch_sha256': file_ref(patch)['sha256'],
              'observation_sha256': file_ref(out / 'observation.json')['sha256']}
    write_json(out / 'report.json', report)
    return report
