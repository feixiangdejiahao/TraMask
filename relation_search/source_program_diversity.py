"""Diversify a source ranking by normalized test syntax and binding scope.

This is an allocation heuristic, not a semantic equivalence proof. Every
candidate remains in later layers. Only the outer test registration name is
normalized; input values, observers, helpers, imports and assertions remain.
"""
from __future__ import annotations

from collections import defaultdict,deque
import hashlib
import json
import posixpath

from anchor_retrieval.syntax import Source,child,walk,literal
from relation_search import oracle


VERSION='scope-aware-source-program-diversity.v1'


def _shape(source,node,ignored):
    if node.id==ignored:return ('test_registration_name',)
    if node.type=='comment':return None
    if not node.children:return (node.type,source.text(node))
    return node.type,tuple(value for part in node.children if (value:=_shape(source,part,ignored)) is not None)


def identity(corpus,candidate):
    candidate=oracle.program_candidate(candidate);test=corpus['tests'][candidate['base_test_id']]
    path=test['span']['path'];row=corpus['sources'][path];language=corpus['language']
    origin=Source(path,row['code'],language,written_path=row.get('written_path'))
    code=oracle.preview(corpus,candidate)
    source=Source(path,('package diversity\n' if language=='go' else '')+code,language)
    if source.root.has_error:return None
    ignored=None
    if language in {'go','python'}:
        roots=[n for n in source.root.named_children if n.type in {'function_declaration','function_definition','decorated_definition'}]
        if len(roots)!=1:return None
        node=roots[0]
        if node.type=='decorated_definition':node=child(node,'definition')
        name=child(node,'name') if node is not None else None
        if name is None:return None
        ignored=name.id
    else:
        statements=[n for n in source.root.named_children if n.type!='comment']
        if len(statements)!=1:return None
        calls=[n for n in walk(statements[0]) if n.type=='call_expression']
        if not calls:return None
        arguments=child(calls[0],'arguments')
        if arguments is None or not arguments.named_children:return None
        first=arguments.named_children[0]
        try:matches=literal(source.text(first))==test['name']
        except ValueError:matches=False
        if not matches:return None
        ignored=first.id
    imports=sorted((name,module,symbol) for name,(module,symbol) in origin.imports.items())
    if language=='go':
        package=next((origin.text(n) for n in origin.root.named_children if n.type=='package_clause'),None)
        if package is None:return None
        scope=dict(package_directory=posixpath.dirname(origin.lookup_path),package=package)
    else:
        enclosing=test.get('enclosing_scope_span',{})
        scope=dict(source_path=path,start=enclosing.get('start_byte'),end=enclosing.get('end_byte'))
    material=dict(language=language,scope=scope,imports=imports,added_imports=candidate.get('imports',[]),
                  normalized_tree=_shape(source,source.root,ignored))
    return hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def diversify(corpus,candidates,ranking):
    groups=defaultdict(deque);unresolved=0
    for position,identifier in enumerate(ranking):
        key=identity(corpus,candidates[identifier])
        if key is None:key='unresolved:'+identifier;unresolved+=1
        groups[key].append(dict(id=identifier,source_rank=position+1,identity=key))
    ordered=[];layer=0
    while any(groups.values()):
        heads=sorted((values[0]['source_rank'],key) for key,values in groups.items() if values)
        for _,key in heads:ordered.append(dict(groups[key].popleft(),layer=layer,rank=len(ordered)+1))
        layer+=1
    return dict(version=VERSION,ranking=ordered,unique_syntax_scopes=len(groups),unresolved=unresolved,
                all_candidates_retained=True,semantic_equivalence_proved=False)
