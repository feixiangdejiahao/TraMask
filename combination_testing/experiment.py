"""Generate and freeze combination tests using only agent-visible inputs.

Execution is a separate command; this module never resolves reference inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from datetime import datetime, timezone

from .paths import generate_paths
from .protocol import generate_protocol
from .structural import generate_structural
from .runner import freeze_artifact
from .contracts import generate_contract_protocol
from .relational import generate_relational

ROOT = Path(__file__).resolve().parents[1]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_case(case: dict, retrieval: Path, output: Path, *, top_k: int = 10,
                  protocol_mode: str = 'empirical', contracts: Path | None = None) -> dict:
    base = ROOT / 'data/cases' / case['id']
    repository = base / 'repository'
    selection = json.loads(retrieval.read_text())
    metadata = {'top_k': top_k, 'retrieval_sha256': _hash(retrieval),
                'candidate_patch_sha256': _hash(base / 'model.patch'),
                'external_model_calls': 0,
                'generator_inputs': ['candidate source', 'retrieved developer/agent tests'],
                'reference_inputs_read': False, 'target_labels_read': False}
    if case['language'] == 'python':
        if protocol_mode == 'contract':
            predicate_path = contracts / case['id'] / 'predicate.py' if contracts else None
            if predicate_path and predicate_path.is_file():
                protocol = generate_contract_protocol(repository, selection, predicate_path, top_k=top_k)
            else:
                # Non-protocol projects still use their own deterministic adapter.
                probe = generate_protocol(repository, selection, top_k=top_k)
                if probe['files']:
                    raise ValueError(f"Missing frozen admission predicate for {case['id']}")
                protocol = probe
        elif protocol_mode == 'relational':
            protocol = generate_relational(repository, selection, top_k=top_k)
        else:
            protocol = generate_protocol(repository, selection, top_k=top_k,
                                         guarded=protocol_mode == 'guarded')
        paths = generate_paths(repository, selection, top_k=top_k)
        files = {**protocol['files'], **paths['files']}
        metadata['generators'] = [
            {**protocol.get('metadata', {}),
             'obligations': protocol.get('obligations', []),
             'controls': protocol.get('controls', []),
             'skipped': protocol.get('skipped', [])},
            {key: value for key, value in paths.items() if key != 'files'},
        ]
        command = 'python3 -m pytest -q ' + ' '.join(shlex.quote(p) for p in sorted(files))
        command += ' --junitxml=/combination-logs/junit.xml'
        report_format, report_path = 'pytest-junit', 'junit.xml'
    else:
        generated = generate_structural(repository, case['language'], selection, top_k=top_k)
        files = generated['files']
        metadata['generators'] = [generated['metadata']]
        command = generated['command']
        report_format, report_path = generated['report_format'], generated['report_path']
    if not files:
        output.mkdir(parents=True, exist_ok=False)
        result = {'case_id': case['id'], 'status': 'unsupported', 'metadata': metadata}
        (output / 'unsupported.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    manifest = freeze_artifact(output, case['id'], files, command, report_format,
                               report_path, timeout=240, metadata=metadata)
    return {'case_id': case['id'], 'status': 'frozen', 'artifact': str(output),
            'manifest_sha256': _hash(output / 'manifest.json'),
            'files': len(manifest['files'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--retrieval', type=Path,
                        default=ROOT / 'results/anchor_retrieval/frontier_final')
    parser.add_argument('--top-k', type=int, default=10)
    parser.add_argument('--protocol-mode', choices=['empirical', 'guarded', 'contract', 'relational'],
                        default='empirical')
    parser.add_argument('--contracts', type=Path)
    args = parser.parse_args()
    policy = json.loads((ROOT / 'configs/execution_policy.json').read_text())
    if not policy['allow_experiment_execution']:
        parser.error('Local experiment execution is not authorized.')
    registry = json.loads((ROOT / 'data/cases.json').read_text())
    cases = [case for case in registry if args.cases is None or case['id'] in args.cases]
    if args.cases and len(cases) != len(set(args.cases)):
        parser.error('Unknown case ID')
    args.output.mkdir(parents=True, exist_ok=False)
    implementation = sorted((ROOT / 'combination_testing').glob('*.py'))
    hashes = {str(path.relative_to(ROOT)): _hash(path) for path in implementation}
    snapshot = args.output / 'implementation_snapshot'
    snapshot.mkdir()
    for path in implementation:
        shutil.copy2(path, snapshot / path.name)
    manifest = {'started_at': datetime.now(timezone.utc).isoformat(),
                'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'git_changes': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True).splitlines(),
                'code_sha256': hashes, 'top_k': args.top_k,
                'protocol_mode': args.protocol_mode,
                'external_model_calls': 0, 'cases': []}
    (args.output / 'generation.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for case in cases:
        result = generate_case(case, args.retrieval / f"{case['id']}.json",
                               args.output / case['id'], top_k=args.top_k,
                               protocol_mode=args.protocol_mode, contracts=args.contracts)
        manifest['cases'].append(result)
        print(json.dumps(result), flush=True)
    current = {str(path.relative_to(ROOT)): _hash(path) for path in implementation}
    if current != hashes:
        raise RuntimeError('Generator changed during generation; retain artifacts but do not call this a frozen algorithm run')
    manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
    (args.output / 'generation.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
