"""Extract declaration signatures and documentation, never implementation bodies."""
from __future__ import annotations

import ast

from anchor_retrieval.syntax import FUNCTIONS, Source, child, walk


def extract_contracts(production_context: dict, language: str, *, max_chars=16000) -> dict:
    declarations, skipped, remaining, seen = [], [], max_chars, set()
    for file in production_context.get('files', []):
        for snippet in file.get('snippets', []):
            code = snippet.get('code', '')
            if not code:
                continue
            try:
                source = Source(file['path'], code, language)
            except (ValueError, TypeError):
                skipped.append({'path': file['path'], 'reason': 'unparseable_snippet'})
                continue
            for node in walk(source.root):
                if node.type not in FUNCTIONS:
                    continue
                body = child(node, 'body')
                if body is None:
                    continue
                signature = source.data[node.start_byte:body.start_byte].decode().strip()
                if len(signature) > 1000:
                    skipped.append({'path': file['path'], 'reason': 'signature_size'})
                    continue
                documentation = ''
                if language == 'python':
                    first = next((n for n in body.named_children if n.type != 'comment'), None)
                    if first is not None and first.type == 'expression_statement' and len(first.named_children) == 1:
                        value = first.named_children[0]
                        if value.type == 'string':
                            try:
                                documentation = ast.literal_eval(source.text(value))
                            except (ValueError, SyntaxError):
                                pass
                else:
                    comments, previous = [], node.prev_named_sibling
                    while previous is not None and previous.type == 'comment':
                        comments.append(source.text(previous))
                        previous = previous.prev_named_sibling
                    documentation = '\n'.join(reversed(comments))
                if not isinstance(documentation, str):
                    documentation = ''
                key = (file['path'], signature, documentation)
                if key in seen:
                    continue
                seen.add(key)
                documentation = documentation[:2000]
                size = len(signature) + len(documentation)
                if size > remaining:
                    skipped.append({'path': file['path'], 'reason': 'contract_context_budget'})
                    continue
                remaining -= size
                declarations.append({'path': file['path'], 'signature': signature,
                                     'documentation': documentation,
                                     'line': snippet.get('start_line', 1) + node.start_point.row})
    return {'declarations': declarations, 'omitted': skipped,
            'provenance': 'Candidate-source documentation and signatures; fallible contract evidence, not a formal specification.',
            'implementation_bodies_included': False, 'max_chars': max_chars}
