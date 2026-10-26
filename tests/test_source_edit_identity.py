import copy

from prototypes.source_edit_identity import distinct_inputs, input_identity


def proposal(identifier='first'):
    return {'id': identifier, 'base_test_id': 'source_test', 'imports': [], 'edits': [
        {'span': {'path': 'source.py', 'start_byte': 10, 'end_byte': 11, 'line': 1},
         'before': '5', 'after': '9'}]}


def test_generator_labels_and_line_annotations_do_not_consume_another_slot():
    first, second = proposal(), proposal('second')
    second['operator'] = 'another_operator'
    second['edits'][0]['span'].pop('line')
    second['edits'][0]['span']['start_line'] = 1
    second['edits'][0]['role'] = 'input'
    kept, duplicates = distinct_inputs([first, second])
    assert kept == [first] and duplicates[0]['id'] == 'second'
    assert distinct_inputs([first, second], ['second'])[0] == []


def test_imports_expected_and_source_identity_are_not_erased():
    original = proposal()
    for field, value in [('base_test_id', 'other'), ('imports', [{'module': 'other', 'name': 'call'}])]:
        changed = copy.deepcopy(original)
        changed[field] = value
        assert input_identity(changed) != input_identity(original)
    changed = copy.deepcopy(original)
    changed['edits'].append({'span': {'path': 'source.py', 'start_byte': 20, 'end_byte': 21},
                            'before': '5', 'after': '9', 'role': 'semantic_expected'})
    assert input_identity(changed) != input_identity(original)
