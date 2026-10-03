"""Recover documentation and type declarations for resolved API boundaries.

The source analyzer supplies exact declaration spans. This retriever does not
guess callees from similar names, copy implementation return values, or execute
code. Documentation can be incomplete or stale and never overrides the issue.
"""
from __future__ import annotations

import hashlib
import json
import posixpath

from anchor_retrieval.syntax import FUNCTIONS, Source, child, walk


VERSION = 'resolved-api-documentation-and-types.v1'
TYPE_KINDS = {'interface_declaration','type_alias_declaration','type_spec','class_definition'}


def _declaration(source, start):
    node = source.root.named_descendant_for_byte_range(start, start)
    while node is not None:
        if node.type in FUNCTIONS | TYPE_KINDS and node.start_byte == start:
            return node
        node = node.parent
    return None


def _documentation(source, node):
    outer = node
    while outer.parent is not None and outer.parent.type in {'export_statement','decorated_definition'}:
        outer = outer.parent
    pieces, current = [], outer
    while current.prev_named_sibling is not None:
        previous = current.prev_named_sibling
        gap = source.data[previous.end_byte:current.start_byte]
        if previous.type != 'comment' or gap.strip() or gap.count(b'\n') > 2:
            break
        pieces.append(dict(start_byte=previous.start_byte,end_byte=previous.end_byte,
                           text=source.text(previous)))
        current = previous
    pieces.reverse()
    body = child(node,'body')
    if source.language == 'python' and body is not None and body.named_children:
        first=body.named_children[0]
        if (first.type=='expression_statement' and len(first.named_children)==1
                and first.named_children[0].type in {'string','concatenated_string'}):
            pieces.append(dict(start_byte=first.start_byte,end_byte=first.end_byte,text=source.text(first)))
    return pieces


def _resolve_type_source(source, name, corpus):
    imported=source.imports.get(name)
    if imported is None:
        return source.path,name
    module,symbol=imported
    if source.language=='typescript' and module.startswith('.'):
        base=posixpath.normpath(posixpath.join(posixpath.dirname(source.lookup_path),module))
        if base.endswith('.js'):
            base=base[:-3]
        paths=[base,base+'.ts',base+'.tsx',base+'/index.ts']
    elif source.language=='python':
        base=module.replace('.','/')
        if module.startswith('.'):
            return None # Relative-import depth is left explicit, not guessed.
        paths=[base+'.py',base+'/__init__.py']
    else:
        return None
    found=[p for p,row in corpus['sources'].items()
           if p in paths or row.get('written_path') in paths]
    return (found[0],symbol or name) if len(found)==1 else None


def collect(corpus, analysis, *, max_bytes=24000, max_types=24):
    parsed, records, unknowns, seen = {}, [], [], set()
    def source(path):
        if path not in parsed:
            row=corpus['sources'][path]
            parsed[path]=Source(path,row['code'],row.get('language',corpus['language']),
                                written_path=row.get('written_path'))
        return parsed[path]
    def add(row):
        key=(row['path'],row['start_byte'],row['end_byte'],row['kind'])
        if key in seen:
            return True
        proposed=records+[row]
        if len(json.dumps(proposed,ensure_ascii=False,separators=(',',':')).encode())>max_bytes:
            unknowns.append(dict(reason='documentation_budget',path=row['path'],start_byte=row['start_byte']))
            return False
        records.append(row);seen.add(key)
        return True
    pending=[]
    for boundary in analysis.get('boundaries',[]):
        ref=boundary.get('declaration_header')
        if not ref:
            continue
        block=analysis['sources'][ref['source']]
        path=block['path']
        if path not in corpus['sources']:
            unknowns.append(dict(reason='declaration_source_not_supplied',path=path));continue
        src=source(path)
        start=block['start_byte']+ref['start'];end=block['start_byte']+ref['end']
        if src.data[start:end].decode()!=block['code'].encode()[ref['start']:ref['end']].decode():
            unknowns.append(dict(reason='declaration_source_span_mismatch',path=path));continue
        node=_declaration(src,start)
        if node is None:
            unknowns.append(dict(reason='declaration_ast_unresolved',path=path,start_byte=start));continue
        docs=_documentation(src,node)
        if docs:
            add(dict(kind='api_documentation',path=path,start_byte=start,end_byte=end,
                     declaration=src.data[start:end].decode(),documentation=docs,
                     source_sha256=hashlib.sha256(src.data).hexdigest(),
                     binding_basis='exact_source_analysis_declaration',
                     contract_status='source_documentation_may_be_stale_issue_takes_precedence'))
        for part in walk(node):
            if part.end_byte<=end and part.type=='type_identifier':
                pending.append((src.path,src.text(part),0))
    visited=set()
    while pending and sum(row['kind']=='type_declaration' for row in records)<max_types:
        path,name,depth=pending.pop(0)
        key=(path,name)
        if key in visited:
            continue
        visited.add(key)
        resolved=_resolve_type_source(source(path),name,corpus)
        if resolved is None:
            continue
        target,symbol=resolved;src=source(target)
        matches=[node for node in walk(src.root) if node.type in TYPE_KINDS
                 and src.text(child(node,'name'))==symbol]
        if len(matches)!=1:
            continue
        node=matches[0]
        # A Python class body is executable implementation, not a type-only
        # declaration. Supply its header and docstring without the body.
        body=child(node,'body')
        end=body.start_byte if src.language=='python' and body is not None else node.end_byte
        code=src.data[node.start_byte:end].decode()
        if add(dict(kind='type_declaration',path=target,start_byte=node.start_byte,end_byte=end,
            symbol=symbol,code=code,documentation=_documentation(src,node),
            source_sha256=hashlib.sha256(src.data).hexdigest(),
            binding_basis='type_name_from_resolved_header_or_type_declaration',
            contract_status='candidate_type_layout_not_expected_runtime_output')) and depth<2:
            pending.extend((target,src.text(part),depth+1) for part in walk(node)
                           if part.type=='type_identifier' and part.end_byte<=end)
    return dict(version=VERSION,records=records,unknowns=unknowns,
        implementation_bodies_used=False,provider_calls=0,execution_outcomes_used=False,
        limitation='Source documentation and types supply API context; no semantic entailment or implementation correctness is proved.')
