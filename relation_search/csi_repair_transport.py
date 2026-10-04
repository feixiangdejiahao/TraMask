"""Verify complete Python test values before running a CSI repair candidate."""
from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

from relation_search.candidate_edit_transport import verify_emission
from relation_search.oracle import preview

VERSION = 'complete-python-value-transport.v1'


def shape(code, name):
    tree = ast.parse(code, type_comments=True)
    matches = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(matches) != 1:
        raise ValueError('Complete Python test registration missing or ambiguous')
    node = copy.deepcopy(matches[0])
    node.name = '__outer_test_registration__'
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def verify(corpus, candidate, artifact):
    prior = verify_emission(corpus, candidate, artifact)
    if prior['status'] != 'matched':
        return prior
    if corpus['language'] != 'python':
        return dict(status='mismatch', reason='strict_repair_transport_requires_python')
    try:
        expected = shape(preview(corpus, candidate), corpus['tests'][candidate['base_test_id']]['name'])
        actual = shape(Path(prior['emitted_source']['path']).read_text(), prior['registration'])
    except (ValueError, SyntaxError) as error:
        return dict(status='mismatch', reason='complete_python_ast_unavailable', detail=str(error))
    if actual != expected:
        return dict(status='mismatch', reason='complete_python_values_or_test_changed', prior_transport=prior)
    return dict(prior, strict_python_transport=VERSION,
                complete_python_ast_sha256=hashlib.sha256(expected.encode()).hexdigest(),
                equivalence='Complete Python AST including every string constant, decorator, setup and assertion; only the outer registration name is normalized.')
