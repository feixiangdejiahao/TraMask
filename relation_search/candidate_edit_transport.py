"""Keep transformed source edits authoritative across native materialization."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from anchor_retrieval.syntax import Source,child,literal,walk
from relation_search import oracle
from scripts.go_materialization import _binary as go_materializer,HELPER as GO_MATERIALIZER_SOURCE


VERSION='rewritten-candidate-transport.v2'
MEASUREMENT_FIELDS={'program_edits','instrumentation','runtime_probes','control_runtime_probes',
                    'source_profile_ids','runtime_profile_limitations'}


def rewrite_view(candidate):
    """Materialize original source edits once, then discard stale probe state.

    Instrumented historical candidates carry both source edits and edits with
    injected loggers. A new structural rewrite needs one authoritative source
    list. Reusing the old instrumentation flag would restore the old snapshot.
    """
    result=oracle.program_candidate(candidate)
    removed=sorted(key for key in MEASUREMENT_FIELDS if key in result)
    for key in removed:result.pop(key)
    result['rewrite_transport']=dict(version=VERSION,removed_measurement_fields=removed,
        source_edit_sha256=hashlib.sha256(json.dumps(result['edits'],sort_keys=True).encode()).hexdigest(),
        execution_probes='disabled_for_this_new_structural_test')
    return result


def _shape(source,node,ignored):
    if node.id==ignored:return ('registration_name',)
    if node.type=='comment':return None
    if not node.children:return node.type,source.text(node)
    return node.type,tuple(item for part in node.children if (item:=_shape(source,part,ignored)) is not None)


def test_shape(code,language,name):
    source=Source('transport',('package transport\n' if language=='go' else '')+code,language)
    if source.root.has_error:raise ValueError('Test source does not parse')
    matches=[]
    for node in walk(source.root):
        if language in {'python','go'} and node.type in {'function_definition','function_declaration','method_declaration'}:
            field=child(node,'name')
            if field is not None and source.text(field)==name:
                outer=node.parent if node.parent is not None and node.parent.type=='decorated_definition' else node
                matches.append((outer,field.id))
        elif language=='typescript' and node.type=='call_expression':
            args=child(node,'arguments')
            if args is not None and args.named_children:
                first=args.named_children[0]
                try:equal=literal(source.text(first))==name
                except (ValueError,TypeError):equal=False
                if equal:matches.append((node,first.id))
    if len(matches)!=1:raise ValueError('Test registration is missing or ambiguous')
    node,ignored=matches[0]
    return _shape(source,node,ignored)


def go_binding_repair(code,name):
    """Replay only Go's parser-bound unused local repair on intended syntax.

    An added blank assignment reads a resolved local identifier. It does not
    repeat its initializer. The parser rejects unsupported initializer/range
    scopes. Other materializer edits remain forbidden by this transport check.
    """
    header='package transport\n'
    request=dict(files=[dict(path='transport_test.go',code=header+code,generated=[name],keep=[name])],prune_history=False)
    process=subprocess.run([str(go_materializer())],input=json.dumps(request),text=True,
                           capture_output=True,check=True,timeout=60)
    records=json.loads(process.stdout)
    if len(records)!=1:raise ValueError('Unexpected binding materialization count')
    record=records[0]
    if record['unsupported']:raise ValueError('Unsupported unused binding scope')
    for edit in record['edits']:
        if (edit['reason']!='preserve_unread_local_binding_without_repeating_initializer'
                or edit['start_byte']!=edit['end_byte'] or edit['before']!=''
                or edit['after']!='; _ = '+edit['name']):
            raise ValueError('Non-binding edit in intended test materialization')
    result=record['code']
    if not result.startswith(header):raise ValueError('Binding materializer changed package header')
    return result[len(header):],dict(edits=record['edits'],
        materializer_sha256=hashlib.sha256(GO_MATERIALIZER_SOURCE.read_bytes()).hexdigest())


def verify_emission(corpus,candidate,artifact):
    """Verify both effective edits and the complete emitted test AST.

    Only the outer registration name and comments are ignored. Go's resolved
    unused local reads are independently replayed on intended source. Other
    helper/call/name rewrites remain a transport mismatch.
    """
    artifact=Path(artifact);read=lambda p:json.loads(Path(p).read_text())
    manifest=read(artifact/'manifest.json');plan=read(artifact/'phase_plan.json')
    accepted=[row for row in read(artifact.parent/'accepted.json') if row['id']==candidate['id']]
    if len(accepted)!=1:return dict(status='mismatch',reason='accepted_candidate_not_unique')
    def edits(rows):
        return sorted((e['span']['path'],e['span']['start_byte'],e['span']['end_byte'],e['before'],e['after']) for e in rows)
    if edits(candidate['edits'])!=edits(oracle.program_candidate(accepted[0])['edits']):
        return dict(status='mismatch',reason='effective_source_edits_changed')
    obligations=[row for row in manifest['obligations'] if row['candidate_id']==candidate['id']]
    if len(obligations)!=1:return dict(status='mismatch',reason='emitted_registration_not_unique')
    obligation=obligations[0]
    phase=next(row for row in plan['phases'] if row['role']=='generated')
    file=next(row for row in phase['files'] if row['target']==obligation['path'])
    mount=next(row for row in manifest['mounts'] if row['target']==file['staged'])
    data=Path(mount['source']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=mount['sha256']:return dict(status='mismatch',reason='emitted_source_receipt_changed')
    expected=oracle.preview(corpus,candidate);original=corpus['tests'][candidate['base_test_id']]['name']
    actual=data.decode();binding_repair=None
    # test_shape supplies a synthetic Go package for a standalone test. Whole
    # emitted Go files already have their package clause; parse those directly.
    if corpus['language']=='go':
        source=Source(obligation['path'],actual,'go')
        nodes=[n for n in source.root.named_children if n.type in {'function_declaration','method_declaration'} and source.text(child(n,'name'))==obligation['test_name']]
        if len(nodes)!=1:return dict(status='mismatch',reason='native_go_test_not_unique')
        actual=source.text(nodes[0])
    try:
        if corpus['language']=='go':expected,binding_repair=go_binding_repair(expected,original)
        expected_shape=test_shape(expected,corpus['language'],original)
        actual_shape=test_shape(actual,corpus['language'],obligation['test_name'])
    except (ValueError,TypeError,KeyError) as error:
        return dict(status='mismatch',reason='test_ast_unavailable',detail=str(error))
    if expected_shape!=actual_shape:return dict(status='mismatch',reason='complete_test_ast_changed')
    return dict(status='matched',version=VERSION,registration=obligation['test_name'],
        emitted_source=dict(path=mount['source'],sha256=mount['sha256']),
        expected_test_sha256=hashlib.sha256(expected.encode()).hexdigest(),
        normalized_test_ast_sha256=hashlib.sha256(json.dumps(expected_shape).encode()).hexdigest(),
        go_binding_repair=binding_repair,
        equivalence='Exact test syntax after independently replayed Go unused local reads, except outer registration name and comments; source input hashes and control execution remain separate requirements.')
