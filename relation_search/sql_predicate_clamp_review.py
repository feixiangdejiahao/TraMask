"""Complete-test admission with independently sourced SQLite reference facts.

Reference facts do not bind the consumer or establish the field's value domain.
The reviewer must discharge those obligations for the actual complete test.
"""
from __future__ import annotations

import json
import sys

from relation_search import compact_admission, compact_contract_guarded as whole_test

VERSION = 'complete-test-sqlite-predicate-clamp-review.v1'
REFERENCE_FACTS = dict(
    version='sqlite-scalar-predicate-reference.v1', checked_date='2026-10-05',
    sources=[
        dict(url='https://www.sqlite.org/lang_corefunc.html#min',
             fact='With at least two arguments, built-in min and max are scalar functions. A one-argument call is aggregate. Scalar min/max select the least/greatest argument.'),
        dict(url='https://www.sqlite.org/lang_corefunc.html#max',
             fact='Scalar max returns NULL if any argument is NULL. Applications can register replacement functions, so actual binding matters.'),
        dict(url='https://www.sqlite.org/datatype3.html#comparison_expressions',
             fact='INTEGER/REAL comparisons are numeric. TEXT/BLOB values use different ordering. Column affinity can coerce comparison operands; adding a scalar function can remove that column affinity.'),
        dict(url='https://www.sqlite.org/lang_expr.html#operators_and_parse_affecting_attributes',
             fact='Ordinary ordered comparisons with NULL return NULL, rather than true or false.'),
        dict(url='https://github.com/sqlite/sqlite/blob/master/src/func.c', symbol='minmaxFunc',
             source_kind='official_dependency_implementation_reference_not_subject_oracle',
             fact='The shared nonaggregate min/max implementation returns without a value if any argument is SQLITE_NULL. This supports NULL propagation in the standard dependency; it does not establish the subject consumer contract.'),
    ],
    conditional_law='For a stable INTEGER/REAL/NULL field x and signed INTEGER bound b, using ordinary built-in SQLite scalar functions and numeric comparison: x<b equals min(x,b)<b; x>b equals max(x,b)>b; x<=b equals max(x,b)<=b; x>=b equals min(x,b)>=b. Both comparisons remain NULL for NULL x.',
    limits='This conditional law does not prove SQLite dialect, callable binding, numeric storage classes, row scope, permitted expression grammar or unchanged complete-test expectations. No TEXT/BLOB, custom function, changed collation or arbitrary SQL equivalence is claimed.',
)
EXTRA_CHECKS = {
    'SQL_DIALECT': dict(kind='required_source_premise', question='Does source/public contract establish that the exact changed argument reaches a SQLite expression consumer, with built-in unoverridden two-argument min/max and unchanged identifier binding? Names or this reference sheet alone do not establish it.'),
    'SQL_VALUES': dict(kind='required_source_premise', question='Are all reached values of the referenced field INTEGER, REAL or NULL with numeric comparison semantics, including existing data and failed-operation paths? A numeric-looking literal, declared column type or function name alone is insufficient; TEXT/BLOB affinity changes stay unknown.'),
    'SQL_CONSUMER': dict(kind='required_source_premise', question='Does the public consumer contract permit this scalar expression and preserve its row/phase meaning? The subject implementation\'s classifier or output is not an oracle. Check empty/multi-row inputs, state changes and every retained expectation.'),
}


def prepare(corpus, frontend, candidate, issue, *, checks=None,
            max_prompt_bytes=64000, max_output_tokens=2048):
    result = whole_test.prepare(corpus, frontend, candidate, issue, checks=checks,
        max_prompt_bytes=sys.maxsize, max_output_tokens=max_output_tokens)
    request = result.get('request')
    if request is None:
        return result
    payload = json.loads(request['prompt'])
    if any(key in payload['checks'] for key in EXTRA_CHECKS):
        raise ValueError('SQL premise check identity conflict')
    payload['sql_predicate_reference'] = REFERENCE_FACTS
    payload['checks'].update(EXTRA_CHECKS)
    prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    size = len(request['system'].encode()) + len(prompt.encode())
    if size > max_prompt_bytes:
        return dict(result, status='unknown_prompt_budget', request=None, prompt_bytes=size,
                    required_bytes=size, max_prompt_bytes=max_prompt_bytes, truncated=False)
    request = dict(request, kind=VERSION, prompt=prompt, prompt_bytes=size,
        check_ids=list(payload['checks']),
        external_roles=[*request['external_roles'], 'independent official SQLite reference facts with explicit domain premises'])
    request['id'] = request['query_sha256'] = whole_test._identity(request)
    return dict(result, request=request, status='prepared', prompt_bytes=size,
                sql_premises_required=list(EXTRA_CHECKS), truncated=False)


def decide(request, payload, *, finish_reason='stop'):
    source = json.loads(request['prompt'])
    if (request.get('kind') != VERSION or request.get('codec_guard', {}).get('allow_prior_gate') is not True
            or source.get('sql_predicate_reference') != REFERENCE_FACTS
            or any(source.get('checks', {}).get(key) != value for key, value in EXTRA_CHECKS.items())
            or request.get('check_ids') != list(source.get('checks', {}))):
        return dict(status='unknown', alarm_eligible=False, semantic_validity='unconfirmed',
                    reason='sql_reference_or_required_premises_changed', request_id=request['id'])
    return compact_admission.decide(request, payload, finish_reason=finish_reason)
