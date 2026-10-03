import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def compile_pair(tmp_path, after, *, worker='compare_typescript_dependency_closure.cjs', limit=128):
    library = os.environ.get('CC_TYPESCRIPT_NODE_PATH')
    if not library or not (Path(library) / 'typescript/lib/typescript.js').exists() or not shutil.which('node'):
        pytest.skip('Supply a local TypeScript package through CC_TYPESCRIPT_NODE_PATH')
    prefix = '''import { good, absent as missing } from './api';
function test(name: string, fn: () => void): void {}
function helper(): number { return unavailable; }
'''
    (tmp_path / 'api.ts').write_text('export function good(): number { return 1; }\n')
    (tmp_path / 'source.ts').write_text(prefix + 'test("selected", () => { good(); });\n')
    (tmp_path / 'before.ts.txt').write_text((tmp_path / 'source.ts').read_text())
    (tmp_path / 'after.ts.txt').write_text(prefix + 'test("selected", () => { ' + after + ' });\n')
    (tmp_path / 'tsconfig.json').write_text(json.dumps({'compilerOptions': {
        'strict': True, 'skipLibCheck': True, 'noEmit': True, 'module': 'esnext', 'target': 'es2022', 'types': []},
        'files': ['source.ts', 'api.ts']}))
    plan = {'target': 'source.ts', 'test_names': ['selected'], 'max_dependency_declarations': limit,
            'phases': [{'role': role, 'files': [{'target': 'source.ts', 'staged': name}]}
                       for role, name in [('control', 'before.ts.txt'), ('generated', 'after.ts.txt')]]}
    (tmp_path / 'plan.json').write_text(json.dumps(plan))
    environment = dict(os.environ, NODE_PATH=library)
    subprocess.run(['node', str(ROOT / 'scripts' / worker), 'plan.json', 'types.json'], cwd=tmp_path,
                   env=environment, check=True, capture_output=True, text=True, timeout=30)
    return json.loads((tmp_path / 'types.json').read_text())


def test_new_use_of_missing_member_is_detected_even_in_a_shared_import(tmp_path):
    old = compile_pair(tmp_path, 'missing();', worker='compare_typescript_programs.cjs')
    new = compile_pair(tmp_path, 'missing();')
    assert old['new_diagnostics'] == []
    assert any(row['code'] == 2305 and row['scope'] == 'local_dependency' for row in new['new_diagnostics'])


def test_new_use_of_an_invalid_helper_expands_its_declaration(tmp_path):
    report = compile_pair(tmp_path, 'helper();')
    assert any(row['code'] == 2304 and row['source'] == 'unavailable' for row in report['new_diagnostics'])


def test_unused_broken_dependencies_do_not_become_new_evidence(tmp_path):
    report = compile_pair(tmp_path, 'good();')
    assert report['status'] == 'compiler_completed'
    assert report['new_diagnostics'] == []


def test_dependency_budget_exhaustion_cannot_look_like_a_clean_type_result(tmp_path):
    report = compile_pair(tmp_path, 'good(); helper(); missing();', limit=1)
    assert report['status'] == 'dependency_closure_incomplete'
