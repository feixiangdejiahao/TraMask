"""Whole-test review with format facts, without a field-domain shortcut."""
from __future__ import annotations

import copy
import json
import sys

from relation_search import compact_contract_guarded as whole_test

VERSION = 'complete-test-unicode-line-field-review.v1'
REFERENCE = dict(
    scope='General language and format facts. These do not prove a target field contract.',
    facts=[
        dict(source='https://www.rfc-editor.org/rfc/rfc8259#section-7',
             fact='JSON permits U+2028 unescaped inside a string. Its string grammar excludes unescaped quotation mark, reverse solidus and U+0000 through U+001F, not U+2028.'),
        dict(source='https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-23/',
             fact='U+2028 is LINE SEPARATOR. It denotes a line boundary in Unicode plain text.'),
        dict(source='https://docs.python.org/3/library/json.html#json.JSONEncoder',
             fact='With ensure_ascii=False, Python JSON serialization emits U+2028 as a literal character. Mandatory JSON escaping still applies.'),
        dict(source='https://docs.python.org/3/library/stdtypes.html#str.splitlines',
             fact='Python str.splitlines recognizes U+2028 as a line boundary. Splitting only on LF is a different operation.'),
    ],
    review_obligations=[
        'Appending U+2028 changes the string value. Do not assume content equivalence or that every string is legal for a public field.',
        'Identify the actual producer, consumer and data format from this complete test and its public source. JSON facts do not establish a JSON pipeline.',
        'Check the public domain of the modified field, including enums, dates, names and embedded syntax. A Python str type alone does not discharge these restrictions.',
        'Check all retained assertions, setup and operations for this exact new value. An unchanged error assertion may remain unrelated to this field.',
        'Use implementation as operation and binding context, not as a correctness oracle. If contract or binding support is missing, return unknown.',
    ],
)


def prepare(corpus, frontend, candidate, issue, *, checks=None,
            max_prompt_bytes=96000, max_output_tokens=16384):
    result = whole_test.prepare(corpus, frontend, candidate, issue, checks=checks,
        max_prompt_bytes=sys.maxsize, max_output_tokens=max_output_tokens)
    request = result.get('request')
    if request is None:
        return result
    payload = json.loads(request['prompt'])
    payload['unicode_line_field_reference'] = copy.deepcopy(REFERENCE)
    prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    size = len(request['system'].encode()) + len(prompt.encode())
    result.update(prompt_bytes=size, truncated=False, unicode_reference_version=VERSION)
    if size > max_prompt_bytes:
        return dict(result, status='unknown_prompt_budget', request=None,
                    alarm_eligible=False, required_bytes=size,
                    max_prompt_bytes=max_prompt_bytes)
    request = dict(request, prompt=prompt, prompt_bytes=size,
                   unicode_reference_version=VERSION,
                   external_roles=[*request['external_roles'], 'official JSON, Unicode and Python format facts; not field-domain proof'])
    request['id'] = request['query_sha256'] = whole_test._identity(request)
    return dict(result, status='prepared', request=request)


def decide(request, payload, *, finish_reason='stop'):
    try:
        reference = json.loads(request['prompt'])['unicode_line_field_reference']
    except (ValueError, KeyError, TypeError):
        reference = None
    if (request.get('unicode_reference_version') != VERSION or reference != REFERENCE):
        return dict(status='unknown', alarm_eligible=False,
                    semantic_validity='unconfirmed', reason='unicode_reference_missing_or_changed',
                    request_id=request['id'])
    return whole_test.decide(request, payload, finish_reason=finish_reason)
