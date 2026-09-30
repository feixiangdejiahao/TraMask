"""Audit sealed finite-pair wires without calling dispatch or reading .env.

The actual provider's payload-building prefix is executed in memory after an
AST allowlist check. File, configuration and network statements are excluded.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def production_payload(request,provider_source):
    module=ast.parse(provider_source)
    function=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
    cut=next(i for i,n in enumerate(function.body) if isinstance(n,ast.Expr) and
             isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='write')
    prefix=copy.deepcopy(function.body[1:cut])
    for node in ast.walk(ast.Module(body=prefix,type_ignores=[])):
        if isinstance(node,(ast.Import,ast.ImportFrom,ast.With,ast.Try,ast.For,ast.While,
                            ast.Lambda,ast.ListComp,ast.DictComp,ast.SetComp,ast.GeneratorExp)):
            raise ValueError('Provider prefix exceeds in-memory payload audit grammar')
        if isinstance(node,ast.Call):
            allowed=(isinstance(node.func,ast.Name) and node.func.id=='ValueError') or (
                isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
                and node.func.value.id=='request' and node.func.attr=='get')
            if not allowed: raise ValueError('Provider prefix contains a non-payload call')
    function=ast.FunctionDef(name='payload_audit',args=ast.arguments(posonlyargs=[],
        args=[ast.arg(arg='request')],vararg=None,kwonlyargs=[],kw_defaults=[],kwarg=None,defaults=[]),
        body=[*prefix,ast.Return(value=ast.Name(id='payload',ctx=ast.Load()))],decorator_list=[],type_params=[])
    isolated=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    scope={'__builtins__':{},'ValueError':ValueError}
    exec(compile(isolated,'provider-payload-prefix','exec'),scope)
    return scope['payload_audit'](request)


def production_encoding(payload,provider_source):
    module=ast.parse(provider_source)
    function=copy.deepcopy(next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='encoded'))
    for node in ast.walk(function):
        if isinstance(node,ast.Call):
            allowed=(isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
                     and node.func.value.id=='json' and node.func.attr=='dumps') or (
                     isinstance(node.func,ast.Attribute) and node.func.attr=='encode')
            if not allowed:raise ValueError('Provider encoding contains a non-serialization call')
    scope={'__builtins__':{},'json':json}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),
                 'provider-encoding-function','exec'),scope)
    return scope['encoded'](payload)


def audit(source,output,provider):
    output.mkdir(parents=True,exist_ok=False)
    ready,protocol=read(source/'ready.json'),read(source/'protocol.json')
    for name,expected in read(source/'seal.json')['files_sha256'].items():
        if digest(source/name)!=expected: raise ValueError('Sealed pair file changed: '+name)
    provider_text=provider.read_text()
    rows=[]
    for record in ready['records']:
        if record['status']!='offerable':
            rows.append(dict(case=record['case'],status=record['status'],offered_members=0))
            continue
        for arm,paths in record['arms'].items():
            request=read(Path(paths['request']))
            expected=production_payload(request,provider_text)
            encoded=production_encoding(expected,provider_text)
            wire=Path(paths['wire_preview'])
            if wire.read_bytes()!=encoded: raise ValueError('Production wire differs from preview: '+record['case']+'/'+arm)
            if digest(wire)!=paths['wire_preview_sha256'] or len(encoded)!=paths['wire_bytes']:
                raise ValueError('Wire hash/byte accounting mismatch')
            if '{"revisions":' in request['system'] or request['system'].count('{"results":')!=1:
                raise ValueError('The system has ambiguous output schemas')
            rows.append(dict(case=record['case'],arm=arm,status='production_wire_exact',
                offered_members=len(request['offered']),wire_sha256=digest(wire),wire_bytes=len(encoded),
                request_sha256=digest(Path(paths['request'])),output_schema='results only'))
    current_code_differences=[name for name,expected in protocol['code_sha256'].items()
        if digest(Path(__file__).resolve().parents[1]/name)!=expected]
    result=dict(status='verified_prepared_wire_identity',pair_source=str(source.resolve()),
        provider_sha256=digest(provider),ready_sha256=digest(source/'ready.json'),
        auditor_script_sha256=digest(Path(__file__)),
        verified_wire_requests=sum(row['status']=='production_wire_exact' for row in rows),
        offered_member_instances=sum(row['offered_members'] for row in rows),rows=rows,
        current_code_differences=current_code_differences,
        runnable_under_current_source=not current_code_differences,
        source_drift_interpretation='Old prepared wires remain auditable, but any changed generating/validation code requires a new sealed input version before execution.',
        denominator_contract='All originally offered members remain in the member denominator. Unknown, omission, format/interface rejection, transport failure and length have zero successful-oracle numerator; not-run is pending, not a final failed trial.',
        request_failure_granularity='A request-level failure applies to every offered member of that request; it never removes those members from its denominator.',
        no_runtime_claim='Input identity and format instructions do not establish oracle correctness, native execution, target detection or actual token cost.',
        provider_calls=0,dispatch_invoked=False,env_read=False,subject_executions=0)
    write(output/'review.json',result)
    return {key:value for key,value in result.items() if key not in ['rows']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--provider',type=Path,default=Path(__file__).resolve().parents[1]/'relational_gap/provider.py')
    args=parser.parse_args()
    print(json.dumps(audit(args.input,args.output,args.provider)))
