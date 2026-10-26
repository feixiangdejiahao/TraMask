from experimental.assertion_path_context import render_context
from test_assertion_write_origin import analyze, LIBRARY


def test_alias_property_helper_and_possible_exit_are_source_excerpts_not_inferred_verdicts():
    library = LIBRARY.replace('obj.done', 'obj._done') + '''
    @property
    def done(obj):
        return obj._done
'''
    result, sources = analyze(library, body='    stream = Channel()\n    alias = stream\n'
                             '    list(alias.consume())\n    list(alias.consume())\n    assert stream.done is True\n')
    text = render_context(sources, result)
    assert 'Direct property alias `done` -> `_done`' in text
    assert '`consume -> finish` via `obj.finish()`' in text
    assert text.count('generator_suspension_or_abandonment, may') == 1
    assert 'not proven evaluation order or branch feasibility' in text
    assert 'alias = stream' in text
    assert text.count('def finish(obj):') == 1
    assert 'not proof of execution' in text
    assert text == render_context(dict(reversed(list(sources.items()))), result)


def test_other_instance_cannot_supply_operation_and_unknown_binding_is_explicit():
    result, sources = analyze(body='    first = Channel()\n    second = Channel()\n'
                              '    list(first.consume())\n    assert second.done is False\n')
    text = render_context(sources, result)
    assert '`consume -> finish` via' not in text
    assert 'first.consume()' in text  # Full source remains visible without claiming a bound path.
    unknown, sources = analyze(body='    stream = factory()\n    assert stream.done\n')
    text = render_context(sources, unknown)
    assert 'Unresolved: unresolved_constructor' in text
    assert 'Bound constructor:' not in text


def test_finally_context_and_terminal_writer_exit_remain_distinguishable():
    protected = LIBRARY.replace('        yield from obj.chunks()\n        obj.finish()',
        '        try:\n            yield from obj.chunks()\n        finally:\n            obj.finish()')
    result, sources = analyze(protected)
    text = render_context(sources, result)
    assert 'call `finish` is inside Try.finalbody' in text
    assert 'Possible source-order exit for call `finish`' not in text
    direct = LIBRARY.replace('        obj.done = True', '        external_step()\n        obj.done = True')
    result, sources = analyze(direct)
    text = render_context(sources, result)
    assert 'Possible source-order exit for field write (call_may_raise, may): `external_step()`' in text
