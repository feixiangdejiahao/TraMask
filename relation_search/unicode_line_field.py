"""Append one Unicode line boundary to a source-bound string field.

The unchanged input-role binder selects locations. No field or API name is an
admission rule. String content changes, so every retained oracle needs a fresh
complete-test contract review.
"""
from __future__ import annotations

import ast
from types import FunctionType

from relation_search import absence_null as source_fields

VERSION = 'source-unicode-line-field-hypotheses.v1'
MAX_CANDIDATES = 16
SUFFIX = '\u2028'
POLICY = dict(
    version=VERSION, language='python', max_candidates=MAX_CANDIDATES,
    construction='Append exactly U+2028 LINE SEPARATOR to one original closed string field value. Render the new Python literal with repr.',
    retrieval='A complete field identifier occurs in the public issue. This retrieves a location; it does not establish its allowed string domain.',
    ordering='retrieval_rank, source path, value start byte',
    containers=source_fields.POLICY['containers'],
    unchanged='The complete original source control and all candidate bytes outside one string literal: decorators, setup, calls, assertions and other values.',
    role_scope=source_fields.POLICY['role_scope'],
    semantics='This changes string content. It is not an equivalence relation. JSON string legality does not establish field legality, parser validity or unchanged expectations.',
    admission='Require a fresh whole-test review of the actual producer, consumer, data format, public field domain and every retained assertion. Enum, date and embedded-language restrictions can reject a candidate.',
    alert='Require repeated source-controlled failure, exact complete Python AST transport and a separate full-test independent audit.',
    development_scope='One development-domain family; no claim of unified novelty or generalization from these trials.',
    forbidden_inputs=source_fields.POLICY['forbidden_inputs'],
)


def _closed_string(node):
    return isinstance(node, ast.Constant) and type(node.value) is str


def generate(corpus, frontend, issue, *, limit=16):
    # Only generate() reads _scalar and VERSION. Its existing helper functions
    # retain the sealed implementation and unchanged role/binding decisions.
    # This private namespace cannot mutate another experiment's module globals.
    namespace = dict(vars(source_fields), _scalar=_closed_string, VERSION=VERSION)
    prior = source_fields.generate
    bound = FunctionType(prior.__code__, namespace, prior.__name__, prior.__defaults__, prior.__closure__)
    bound.__kwdefaults__ = prior.__kwdefaults__
    result = bound(corpus, frontend, issue, limit=limit)
    for candidate in result['candidates']:
        edit = candidate['edits'][0]
        original = ast.literal_eval(edit['before'])
        if type(original) is not str:
            raise ValueError('Source binder returned a non-string field')
        edit['after'] = repr(original + SUFFIX)
        candidate.update(id='unicodefield_' + source_fields.digest(
            [VERSION, candidate['base_test_id'], edit])[:24],
            operator='append_unicode_line_separator_to_source_string_field')
        evidence = candidate['source_evidence']
        evidence.pop('null_illegality_established')
        evidence.update(transformation=dict(operation='append', code_point='U+2028',
            unicode_name='LINE SEPARATOR', before=original, after=original+SUFFIX),
            content_equivalence_claimed=False,
            field_domain_established=False,
            complete_oracle_validity_established=False)
    result['catalog'] = [dict(candidate_id=c['id'], **c['source_evidence'])
                         for c in result['candidates']]
    return result
