"""Receiver-dispatch source facts only; no miniature subject is executed."""
from __future__ import annotations

import pytest

from anchor_retrieval.syntax import Source
from experimental.source_receiver_binding import dispatch_unknown
from relational_gap.frontend import _FrontendIndex, _parameters, _flow_for_test, _test_walk


PLAIN = "class Box:\n    def compute(owner, value):\n        return value * 3\n"
EXTRA = "\ndef neutral(value):\n    return value\nclass Other:\n    def compute(owner,value):\n        return value\n"
BODY = "instance = Box()\nvalue = 11\nresult = instance.compute(value)\nassert result == 33"


def fixture(library=PLAIN, body=BODY, prefix="", suffix="", imports="Box, Other, neutral"):
    source = Source('library.py', library + EXTRA, 'python')
    test = Source('test_source.py', 'from library import ' + imports + '\n' + prefix
                  + 'def test_review():\n' + ''.join('    ' + line + '\n' for line in body.splitlines())
                  + suffix, 'python')
    index = _FrontendIndex([source, test], '')
    for unit in index.units.values():
        unit.params = [p['name'] for p in _parameters(unit) if p['name'] is not None]
    index.flows = {}
    target = next(unit for unit in index.units.values() if unit.owner == 'Box' and unit.name == 'compute')
    caller = next(unit for unit in index.units.values() if unit.name == 'test_review')
    flow = _flow_for_test(index, caller, list(_test_walk(caller.body)))
    call = next(call for call in reversed(flow.calls) if call.name.endswith('.compute'))
    return index, caller, flow, call, target


def reason(*args, **kwargs):
    return dispatch_unknown(*fixture(*args, **kwargs))


def test_plain_source_receiver_remains_supported():
    assert reason() is None


def test_plain_local_alias_remains_supported():
    body = BODY.replace('value = 11', 'alias = instance\nvalue = 11').replace('instance.compute', 'alias.compute')
    assert reason(body=body) is None


@pytest.mark.parametrize('decorator', ['staticmethod', 'classmethod'])
def test_builtin_descriptors_are_supported_when_not_shadowed(decorator):
    parameters = 'value' if decorator == 'staticmethod' else 'class_arg, value'
    source = f'class Box:\n    @{decorator}\n    def compute({parameters}):\n        return value * 3\n'
    assert reason(source) is None
    assert reason(source, BODY.replace('instance.compute(value)', 'Box.compute(value)')) is None


def test_explicit_unbound_class_lookup_remains_supported():
    assert reason(body=BODY.replace('instance.compute(value)', 'Box.compute(instance, value)')) is None


def test_target_member_rebinding_in_class_namespace_is_unknown():
    source = PLAIN + '    def alternate(owner,value):\n        return value\n    compute = alternate\n'
    assert reason(source) == 'receiver_class_member_rebound'


def test_class_decorator_that_replaces_class_is_unknown():
    source = 'def replace_class(original):\n    return Other\n@replace_class\n' + PLAIN
    assert reason(source) == 'receiver_class_decorator_unknown'


@pytest.mark.parametrize('member_decorator', ['property', 'custom'])
def test_custom_property_or_member_descriptor_is_unknown(member_decorator):
    source = PLAIN.replace('    def compute', '    @' + member_decorator + '\n    def compute')
    assert reason(source) == 'receiver_member_descriptor_unknown'


@pytest.mark.parametrize('decorator', ['staticmethod', 'classmethod'])
def test_class_or_module_descriptor_shadow_is_unknown(decorator):
    source = 'custom = neutral\n' + PLAIN.replace('    def compute', '    @' + decorator + '\n    def compute')
    assert reason(decorator + '= custom\n' + source) == 'receiver_descriptor_builtin_shadowed'
    source = source.replace('class Box:\n', 'class Box:\n    ' + decorator + '=custom\n')
    assert reason(source) == 'receiver_descriptor_builtin_shadowed'


def test_visible_receiver_member_write_is_unknown():
    body = BODY.replace('value = 11', 'instance.compute = neutral\nvalue = 11')
    assert reason(body=body) == 'receiver_prior_effect_or_alias_unknown'


def test_alias_write_before_call_is_seen_even_if_flow_does_not_update_original_name():
    body = BODY.replace('value = 11', 'alias = instance\nalias.compute = neutral\nvalue = 11')
    assert reason(body=body) == 'receiver_visible_member_write'


def test_different_fresh_object_write_is_not_conflated_with_receiver():
    body = BODY.replace('value = 11', 'other = Box()\nother.compute = neutral\nvalue = 11')
    assert reason(body=body) is None


def test_old_alias_rebound_to_new_object_does_not_contaminate_receiver():
    body = BODY.replace('value = 11', 'alias = instance\nalias = Other()\nalias.compute = neutral\nvalue = 11')
    assert reason(body=body) is None


def test_receiver_member_write_after_call_does_not_change_that_call():
    assert reason(body=BODY + '\ninstance.compute = neutral') is None


@pytest.mark.parametrize('prefix,suffix', [('Box.compute = neutral\n', ''), ('', '\nBox.compute = neutral\n')])
def test_test_module_class_member_monkeypatch_is_unknown_even_after_test_definition(prefix, suffix):
    assert reason(prefix=prefix, suffix=suffix) == 'receiver_module_member_write'


def test_production_module_class_member_monkeypatch_is_unknown():
    assert reason(PLAIN + '\nBox.compute = neutral\n') == 'receiver_module_member_write'


def test_local_class_member_write_is_unknown_for_unbound_lookup():
    body = BODY.replace('value = 11', 'Box.compute = neutral\nvalue = 11').replace('instance.compute(value)', 'Box.compute(instance, value)')
    assert reason(body=body) == 'receiver_visible_class_member_write'


def test_different_import_spellings_of_same_class_do_not_hide_class_write():
    body = BODY.replace('Box()', 'Alias()').replace('value = 11', 'Box.compute = neutral\nvalue = 11')
    assert reason(body=body, imports='Box, Box as Alias, Other, neutral') == 'receiver_visible_class_member_write'


def test_unresolved_module_class_alias_write_is_unknown():
    assert reason(prefix='Alias = Box\nAlias.compute = neutral\n') == 'receiver_module_member_alias_unknown'


def test_distinct_imported_class_member_write_does_not_change_target_class():
    assert reason(prefix='Other.compute = neutral\n') is None


def test_local_parameter_name_does_not_hide_module_class_member_write():
    index, caller, flow, call, target = fixture(prefix='Box.compute = neutral\n')
    caller.params.append('Box')
    assert dispatch_unknown(index, caller, flow, call, target) == 'receiver_module_member_write'


@pytest.mark.parametrize('receiver', ['self', 'object_arg'])
def test_constructor_member_overwrite_is_unknown_for_any_receiver_spelling(receiver):
    source = PLAIN.replace('class Box:\n', f'class Box:\n    def __init__({receiver}):\n        {receiver}.compute = neutral\n')
    assert reason(source) == 'receiver_constructor_member_write'


def test_constructor_alias_member_overwrite_is_unknown():
    source = PLAIN.replace('class Box:\n', 'class Box:\n    def __init__(owner):\n        alias=owner\n        alias.compute=neutral\n')
    assert reason(source) == 'receiver_constructor_member_write'


def test_constructor_class_alias_write_also_changes_explicit_class_lookup():
    source = PLAIN.replace('class Box:\n', 'class Box:\n    def __init__(owner):\n        alias=Box\n        alias.compute=neutral\n')
    assert reason(source, BODY.replace('instance.compute(value)', 'Box.compute(instance, value)')) == 'receiver_constructor_class_member_write'


def test_constructor_unrelated_scalar_field_write_is_supported():
    source = PLAIN.replace('class Box:\n', 'class Box:\n    def __init__(owner):\n        owner.value=1\n')
    assert reason(source) is None


def test_constructor_receiver_escape_is_unknown():
    source = PLAIN.replace('class Box:\n', 'class Box:\n    def __init__(owner):\n        external(owner)\n')
    assert reason(source) == 'receiver_constructor_opaque_escape'


def test_instance_member_override_does_not_replace_explicit_class_lookup():
    source = PLAIN.replace('class Box:\n', 'class Box:\n    def __init__(owner):\n        owner.compute=neutral\n')
    assert reason(source, BODY.replace('instance.compute(value)', 'Box.compute(instance, value)')) is None


@pytest.mark.parametrize('operation', ['external(instance)', 'instance.configure()'])
def test_prior_receiver_opaque_effect_is_unknown(operation):
    body = BODY.replace('value = 11', operation + '\nvalue = 11')
    assert reason(body=body) == 'receiver_prior_effect_or_alias_unknown'


def test_prior_alias_escape_is_seen_even_without_receiver_name_effect_edge():
    body = BODY.replace('value = 11', 'alias=instance\nexternal(alias)\nvalue = 11')
    assert reason(body=body) == 'receiver_prior_opaque_escape'


def test_prior_unrelated_object_escape_does_not_contaminate_receiver():
    body = BODY.replace('value = 11', 'other=Other()\nexternal(other)\nvalue = 11')
    assert reason(body=body) is None


@pytest.mark.parametrize('hook', ['__new__', '__getattribute__', '__getattr__', '__setattr__'])
def test_custom_python_lookup_and_allocation_hooks_are_unknown(hook):
    source = PLAIN.replace('class Box:\n', 'class Box:\n    def ' + hook + '(owner, *args):\n        return neutral\n')
    assert reason(source) == 'receiver_custom_lookup_or_allocation_unknown'


@pytest.mark.parametrize('header,expected', [
    ('class Box(Other):', 'receiver_inherited_dispatch_unknown'),
    ('class Box(metaclass=Unknown):', 'receiver_metaclass_unknown'),
])
def test_unproved_inheritance_or_metaclass_dispatch_is_unknown(header, expected):
    assert reason(PLAIN.replace('class Box:', header)) == expected


def test_explicit_unshadowed_builtin_object_base_is_supported():
    assert reason(PLAIN.replace('class Box:', 'class Box(object):')) is None


def test_keyword_only_actuals_do_not_change_this_dispatch_guard():
    assert reason(body=BODY.replace('instance.compute(value)', 'instance.compute(value=value)')) is None
