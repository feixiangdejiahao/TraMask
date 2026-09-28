import json
from pathlib import Path

from relational_gap.frontend import extract_frontend
from relational_gap.inputs import select_sources


def test_historical_lookup_is_relative_and_existing_test_suffix_is_preserved(tmp_path):
    repository = tmp_path / 'repository'
    repository.mkdir()
    (repository / 'ops.ts').write_text('export function step(value: number) { return value + 1; }')
    patch = tmp_path / 'patch.diff'
    patch.write_text('')
    trajectory = tmp_path / 'trajectory.json'
    code = "import {test,expect} from 'vitest'; import {step} from '../ops'; test('old',()=>{expect(step(2)).toBe(3);});"
    trajectory.write_text(json.dumps({'steps': [{'step_id': 1, 'tool_calls': [{'arguments': {
        'command': "cat > /app/tests/value.unit.test.ts <<'EOF'\n" + code + '\nEOF'
    }}]}]}))
    case = {'repository': str(repository), 'language': 'typescript',
            'candidate_patch': str(patch), 'trajectory': str(trajectory)}
    sources, selected = select_sources(case)
    historical, = [source for source in sources if source.origin == 'trajectory']
    assert historical.path.endswith('_value.unit.test.ts')
    assert '.test.test.ts' not in historical.path
    assert historical.lookup_path == 'tests/value.unit.test.ts'
    metadata = selected['files'][historical.path]
    assert metadata['original_written_path'] == '/app/tests/value.unit.test.ts'
    frontend = extract_frontend(sources)
    call = next(c for c in frontend['calls'] if c['callee'] == 'step')
    assert any(target['resolved'] for target in call['targets'])
