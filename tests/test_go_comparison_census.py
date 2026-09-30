"""Qualify source region selection before the prospective Go probe census."""
import copy

import pytest

from scripts.census_go_comparison_probes import _safe_path, select_functions


def _corpus(code, path='library.go', **metadata):
    return dict(language='go', sources={path: dict(code=code, **metadata)})


def _patch(path, line, before, after):
    return f'diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -{line},1 +{line},1 @@\n-{before}\n+{after}\n'


def test_exact_new_source_line_selects_only_containing_function():
    code = 'package example\nfunc one(x int) bool { return x < 4 }\nfunc two(x int) bool { return x <= 8 }\n'
    corpus = _corpus(code)
    snapshot = copy.deepcopy(corpus)
    sources, selected, unknowns = select_functions(corpus, _patch('library.go', 3,
        'func two(x int) bool { return x < 8 }', 'func two(x int) bool { return x <= 8 }'))
    assert len(selected) == 1 and selected[0]['line'] == 3
    extent = selected[0]
    assert sources[0].data[extent['start_byte']:extent['end_byte']].decode().startswith('func two(')
    assert extent['verified_patch_lines'] == [3]
    assert not unknowns
    assert corpus == snapshot


def test_nonmatching_submitted_source_does_not_select_stale_code():
    corpus = _corpus('package example\nfunc one(x int) bool { return x < 4 }\n')
    _, selected, unknowns = select_functions(corpus, _patch('library.go', 2,
        'func one(x int) bool { return x < 4 }', 'func one(x int) bool { return x <= 4 }'))
    assert selected == []
    assert any(row['reason'] == 'patch_new_line_source_mismatch' for row in unknowns)


def test_deletion_boundary_is_not_a_modified_production_instruction():
    corpus = _corpus('package example\nfunc one(x int) bool { return x < 4 }\n')
    patch = '--- a/library.go\n+++ b/library.go\n@@ -2,2 +2,1 @@\n-func old() {}\n func one(x int) bool { return x < 4 }\n'
    _, selected, unknowns = select_functions(corpus, patch)
    assert selected == []
    assert any('delet' in row['reason'] for row in unknowns)


def test_changed_test_file_is_never_selected_as_production():
    code = 'package example\nfunc Check(x int) bool { return x < 4 }\n'
    _, selected, _ = select_functions(_corpus(code, 'library_test.go'),
        _patch('library_test.go', 2, 'func Check(x int) bool { return x < 3 }',
               'func Check(x int) bool { return x < 4 }'))
    assert selected == []


def test_trajectory_copy_cannot_supply_verified_repository_code():
    code = 'package example\nfunc Check(x int) bool { return x < 4 }\n'
    sources, selected, unknowns = select_functions(_corpus(code, origin='trajectory'),
        _patch('library.go', 2, 'func Check(x int) bool { return x < 3 }',
               'func Check(x int) bool { return x < 4 }'))
    assert sources == selected == []
    assert any(row['reason'] == 'patch_final_repository_source_unavailable' for row in unknowns)


@pytest.mark.parametrize('metadata', [{'complete_file': False}, {'parse_error': True}])
def test_incomplete_source_keeps_explicit_unknown(metadata):
    sources, selected, unknowns = select_functions(_corpus('package example\n', **metadata), '')
    assert sources == selected == []
    assert {'path': 'library.go', 'reason': 'incomplete_or_failed_source_parse'} in unknowns
    assert {'reason': 'no_available_modified_source_line'} in unknowns


def test_other_languages_remain_in_denominator_as_unsupported():
    sources, selected, unknowns = select_functions(dict(language='typescript', sources={}), '')
    assert sources == selected == []
    assert unknowns == [{'reason': 'language_not_supported', 'language': 'typescript'}]


def test_import_edit_does_not_instrument_every_function_in_file():
    code = 'package example\nimport "fmt"\nfunc one(x int) bool { return x < 4 }\n'
    _, selected, _ = select_functions(_corpus(code), _patch('library.go', 2,
        'import "os"', 'import "fmt"'))
    assert selected == []


@pytest.mark.parametrize('path', ['/tmp/out.go', '../out.go', 'pkg/../../out.go'])
def test_output_paths_cannot_escape_prospective_tree(path):
    with pytest.raises(ValueError, match='unsafe_output_source_path'):
        _safe_path(path)


def test_utf8_offsets_select_original_function_bytes():
    code = 'package example\n// 观察\nfunc two(x int) bool { return x <= 8 }\n'
    sources, selected, _ = select_functions(_corpus(code), _patch('library.go', 3,
        'func two(x int) bool { return x < 8 }', 'func two(x int) bool { return x <= 8 }'))
    extent = selected[0]
    assert extent['start_byte'] > code.index('func two')
    assert sources[0].data[extent['start_byte']:extent['end_byte']].decode() == 'func two(x int) bool { return x <= 8 }'
