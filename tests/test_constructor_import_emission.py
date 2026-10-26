"""Both emission routes must retain the donor module's resolved identity."""
import json
import posixpath
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source, units
from prototypes.relation_search_go_ts import emit_neighbors, propose_neighbors
from generic_composition.emitter import emit


@pytest.mark.parametrize('target_path', [
    'tests/runtime/case.test.ts',
    'src/wrapper/case.test.ts',
    'case.test.ts',
])
def test_constructor_import_origin_survives_both_emitters(tmp_path, target_path):
    donor = Source('src/consumer/types.test-d.ts',
        'import {base, wrap} from "../wrapper/index.mjs";'
        'test("types",()=>{const item=wrap(base());});', 'typescript')
    module = posixpath.relpath('src/wrapper/index.mjs', posixpath.dirname(target_path) or '.')
    module = module if module.startswith('.') else './' + module
    target = Source(target_path,
        'import {base} from ' + json.dumps(module) + ';'
        'test("runtime",()=>{const wrap=5;const item=base();'
        'if(item.value!==9)throw Error("bad value");});', 'typescript')
    row, = propose_neighbors(target, [donor], operators=['constructor_wrap'])
    requested, = row['imports']
    assert requested['module'] == '../wrapper/index.mjs'
    assert requested['source_path'] == donor.path
    assert requested['name'] != 'wrap'  # The recipient local must remain intact.

    direct, _ = emit_neighbors(target, [row])
    unit = next(unit for unit in units(target)[0] if unit.test)
    corpus = dict(language='typescript', sources={target.path: dict(code=target.code)},
        tests={'seed': dict(name=unit.name, span=dict(path=target.path,
            start_byte=unit.node.start_byte, end_byte=unit.node.end_byte))})
    generic = emit(corpus, [dict(row, base_test_id='seed')])
    assert generic['unsupported'] == []
    generic_code = generic['files'][target.path]
    for code in [direct, generic_code]:
        imported = Source(target.path, code, 'typescript').imports[requested['name']]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(target.path), imported[0]))
        assert (resolved, imported[1]) == ('src/wrapper/index.mjs', 'wrap')

    if shutil.which('node') is None:
        pytest.skip('node is required for the independent import execution')
    library = tmp_path / 'src/wrapper/index.mjs'
    library.parent.mkdir(parents=True, exist_ok=True)
    library.write_text('export const base=()=>({value:9}); export const wrap=x=>x;')
    for index, code in enumerate([direct, generic_code]):
        filename = (tmp_path / target.path).with_suffix('.mjs')
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_text('const executed=[]; function test(name,fn){fn();executed.push(name)}\n'
                            + code + '\nconsole.log(executed.length);')
        result = subprocess.run(['node', str(filename)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(2 if index == 0 else 3)
