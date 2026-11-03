"""Compare pytest-rewritten bytecode to saved source, without executing it."""
import ast
import base64
import importlib.util
import json
import marshal
import sys
import types


def verify(request,store_type):
    blobs=store_type(request['blobs']);results={};checked={}
    for item in request['entries']:
        key=(item['cache'],tuple(item['sources']),item['rewrite'],item['optimize'])
        if key in checked:
            results[item['event']]=checked[key];continue
        raw=blobs.read(item['cache'])
        basis='pytest_bytecode_equivalence' if item['rewrite'] else 'bytecode_equivalence'
        if raw[:4]!=importlib.util.MAGIC_NUMBER:
            results[item['event']]=checked[key]={'matched_sources':[],'basis':basis,'reason':'python_bytecode_version_differs'};continue
        try:cached=marshal.loads(raw[16:])
        except (EOFError,ValueError,TypeError) as error:
            results[item['event']]=checked[key]={'matched_sources':[],'basis':basis,'reason':str(error)};continue
        if not isinstance(cached,types.CodeType):
            results[item['event']]=checked[key]={'matched_sources':[],'basis':basis,'reason':'not_python_code'};continue
        matches=[]
        for digest in item['sources']:
            source=base64.b64decode(request['sources'][digest])
            try:
                tree=ast.parse(source,filename=cached.co_filename)
                if item['rewrite']:
                    from _pytest.assertion.rewrite import rewrite_asserts
                    rewrite_asserts(tree,source,cached.co_filename)
                compiled=compile(tree,cached.co_filename,'exec',dont_inherit=True,optimize=item['optimize'])
                if compiled==cached:matches.append(digest)
            except (SyntaxError,UnicodeError):continue
        results[item['event']]={'matched_sources':matches,'basis':basis}
        if not matches:results[item['event']]['reason']='no_saved_source_matches_cached_code'
        checked[key]=results[item['event']]
    return results


