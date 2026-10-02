"""A single source-only prior: an edited, observed call named by the issue.

This module only partitions an existing ranking. It never judges an oracle,
executes a test, or reads an evaluation label or model response.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re

from anchor_retrieval.syntax import ATTRS, CALLS, Source, attr_parts, call_parts, child, walk
from relation_search.admission import program_candidate
from relation_search import semantic_selection


POLICY = dict(
    version='edited-contract-call-priority-v1',
    feature='one non-oracle edit affects an issue-named call argument, and that same call is observed',
    issue_names='exact inline-code identifier chains or call names inside inline/fenced code; no prose keyword scores',
    resolution='unchanged source-resolved callee with unchanged receiver binding, or unshadowed explicit import',
    input_reach='direct argument edit or one directly preceding local assignment used by that argument',
    observation='frontend actual expression after span mapping: same nested call, one assigned return, or same unrebound receiver field',
    scope='modified owner only; existing frontend symbols; no production reachability or helper expansion',
    ordering='stable true-first partition of complete existing source-shape ranking',
    unknown='retain in original relative order; no priority; absence is not independence or invalidity',
    forbidden_inputs=['positive IDs','target ranks','manual labels','model responses','native failure text','oracle cache'],
    patch_used=False,
)

FUNCTIONS = {'function_definition','function_declaration','method_definition','method_declaration',
             'function_expression','arrow_function','lambda','func_literal'}
IDENTIFIER = re.compile(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*')
CALL_NAME = re.compile(r'(?<![\w$])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def issue_names(issue):
    names=set()
    fenced=re.findall(r'```[^\n]*\n(.*?)```',issue,flags=re.S)
    remaining=re.sub(r'```.*?```','',issue,flags=re.S)
    for code in re.findall(r'`([^`\n]+)`',remaining):
        value=code.strip()
        if IDENTIFIER.fullmatch(value):
            names.add(value)
        names.update(CALL_NAME.findall(value))
    for code in fenced:
        names.update(CALL_NAME.findall(code))
    return sorted(names)


def _inside(outer,inner):
    return outer[0]<=inner[0] and inner[1]<=outer[1]


def _extent(node):
    return node.start_byte,node.end_byte


def _overlap(left,right):
    if left[0]==left[1]:
        return right[0]<=left[0]<right[1]
    return left[0]<right[1] and right[0]<left[1]


def _mapped(extent,edits):
    """Map surviving or enclosing original extents; never guess inside replacements."""
    start,end=extent;delta_before=delta_inside=0
    for edit in edits:
        a,b=edit['old'];delta=edit['new'][1]-edit['new'][0]-(b-a)
        if b<=start:
            delta_before+=delta
        elif a>=end:
            continue
        elif start<=a and b<=end:
            delta_inside+=delta
        else:
            return None
    return start+delta_before,end+delta_before+delta_inside


def _scope(node):
    current=node.parent
    while current is not None:
        if current.type in FUNCTIONS:
            return _extent(current)
        current=current.parent
    return None


def _statement(node):
    current=node
    while current.parent is not None and current.parent.type not in {'block','statement_block','statement_list','module','program','source_file'}:
        current=current.parent
    return current


def _read_names(source,node):
    result=set()
    for part in walk(node):
        if part.type!='identifier':
            continue
        parent=part.parent
        if parent is not None and parent.type in ATTRS and attr_parts(parent)[1]==part:
            continue
        result.add(source.text(part))
    return result


def _assignments(source,root):
    result=[]
    for node in walk(root):
        if node.type not in {'assignment','annotated_assignment','short_var_declaration','var_spec','variable_declarator','assignment_expression'}:
            continue
        left,right=child(node,'left','name'),child(node,'right','value')
        if left is None or right is None:
            continue
        if left.type in {'expression_list','pattern_list'} and len(left.named_children)==1:
            left=left.named_children[0]
        if right.type=='expression_list' and len(right.named_children)==1:
            right=right.named_children[0]
        if left.type!='identifier':
            continue
        statement=_statement(node)
        result.append(dict(name=source.text(left),node=node,value=right,scope=_scope(node),
                           statement=statement,block=_extent(statement.parent) if statement.parent else None))
    return result


def _binding(assignments,name,at):
    candidates=[row for row in assignments if row['name']==name and row['node'].end_byte<=at.start_byte
                and row['scope']==_scope(at)]
    if not candidates:
        return None
    latest=max(candidates,key=lambda row:row['node'].start_byte)
    statement=_statement(at)
    if statement.parent is None or latest['block']!=_extent(statement.parent):
        return None
    return latest


def _binding_key(assignments,name,node):
    value=_binding(assignments,name,node)
    if value:return _extent(value['node'])
    if any(row['name']==name and row['scope']==_scope(node) and row['node'].end_byte<=node.start_byte for row in assignments):
        return None
    return 'unbound',_scope(node),name


def _chain(source,node):
    if node is None:
        return None
    value=source.text(node)
    return value.split('.') if IDENTIFIER.fullmatch(value) else None


def _identity_names(identity):
    if not identity:
        return set()
    pieces=re.split(r'[/:]',identity)
    result={identity}
    result.update(piece for piece in pieces if IDENTIFIER.fullmatch(piece))
    for piece in tuple(result):
        if IDENTIFIER.fullmatch(piece):
            bits=piece.split('.')
            result.update('.'.join(bits[i:]) for i in range(len(bits)))
    return result


class Analyzer:
    def __init__(self,corpus,frontend,issue):
        self.corpus=corpus;self.frontend=frontend;self.names=issue_names(issue)
        self.calls=defaultdict(list);self.observations=defaultdict(list)
        self.functions={row['id']:row for row in frontend.get('functions',[])}
        for row in frontend.get('calls',[]):self.calls[row['test_id']].append(row)
        for row in frontend.get('observations',[]):
            if row.get('kind')=='assertion':self.observations[row['test_id']].append(row)
        self.original={}

    def _source(self,candidate):
        test=self.corpus['tests'][candidate['base_test_id']];path=test['span']['path']
        if path not in self.original:
            self.original[path]=Source(path,self.corpus['sources'][path]['code'],self.corpus['language'])
        original=self.original[path];data=original.data;offset=0;changes=[];previous=-1
        for i,edit in sorted(enumerate(candidate['edits']),key=lambda pair:(pair[1]['span']['path'],pair[1]['span']['start_byte'])):
            if edit['span']['path']!=path:raise ValueError('cross_file_edit_unresolved')
            a,b=edit['span']['start_byte'],edit['span']['end_byte']
            if not 0<=a<=b<=len(data) or a<previous or data[a:b].decode()!=edit['before']:
                raise ValueError('invalid_or_overlapping_edit')
            changes.append(dict(index=i,old=(a,b),new=(a+offset,a+offset+len(edit['after'].encode())),
                                role=edit.get('role','input'),before=edit['before'],after=edit['after']))
            offset+=len(edit['after'].encode())-(b-a);previous=b
        for edit in reversed(changes):
            a,b=edit['old'];data=data[:a]+edit['after'].encode()+data[b:]
        source=Source(path,data.decode(),self.corpus['language'])
        for imported in candidate.get('imports',[]):source.imports[imported['name']]=(imported['module'],imported.get('imported_name'))
        if source.root.has_error:raise ValueError('modified_parse_error')
        extent=_mapped((test['span']['start_byte'],test['span']['end_byte']),changes)
        if extent is None:raise ValueError('modified_test_extent_unresolved')
        return original,source,changes,extent

    def _resolve(self,source,call,assignments,original_calls,changes):
        fn,_=call_parts(call);parts=_chain(source,fn)
        if not parts:return None
        # Imports prove only names; local rebinding defeats that proof.
        rebound=any(row['name']==parts[0] and row['scope']==_scope(call) for row in assignments)
        if parts[0] in source.imports and not rebound:
            module,name=source.imports[parts[0]]
            canonical='.'.join([module]+([name] if name else [])+parts[1:])
            return dict(identity=canonical,names=sorted(_identity_names(canonical)),basis='explicit_unrebound_import')
        matches=original_calls.get(_extent(call),[])
        if len(matches)!=1:return None
        old=matches[0]
        if old.get('callee')!=source.text(fn):return None
        # An argument edit can preserve a callee; a receiver-defining edit cannot.
        if len(parts)>1:
            binding=_binding(assignments,parts[0],call)
            if binding and any(_overlap(edit['new'],_extent(binding['value'])) for edit in changes):return None
        elif rebound:
            return None
        canonical=(old.get('callee_identity') or {}).get('canonical')
        targets=[target for target in old.get('targets',[]) if target.get('resolved') is True
                 and target.get('function_id') in self.functions]
        identities=[]
        for target in targets:
            row=self.functions[target['function_id']]
            if row.get('owner'):identities.append(row['owner']+'.'+row['name'])
            else:identities.append(row['name'])
        identities=sorted(set(identities))
        if canonical:
            identities.append(canonical)
        if not identities:return None
        # Multiple distinct resolved source declarations do not establish one API.
        target_ids={target['function_id'] for target in targets}
        if len(target_ids)>1:return None
        return dict(identity=canonical or identities[0],names=sorted(set().union(*(_identity_names(v) for v in identities))),
                    basis='unchanged_frontend_callee_and_receiver_binding')

    def evidence(self,raw):
        candidate=program_candidate(raw);base=candidate['base_test_id']
        result=dict(feature=False,status='no_witness',witnesses=[],unknowns=[])
        if not self.names:return dict(result,status='no_issue_code_api_names')
        try:
            _,source,changes,test_extent=self._source(candidate)
            nodes=[node for node in walk(source.root) if _inside(test_extent,_extent(node))]
            assignments=[row for row in _assignments(source,source.root) if _inside(test_extent,_extent(row['node']))]
            exact={_extent(node):node for node in nodes}
            calls=[node for node in nodes if node.type in CALLS]
            original_calls=defaultdict(list)
            for row in self.calls[base]:
                position=row['span']
                if position['path']==source.path:
                    mapped=_mapped((position['start_byte'],position['end_byte']),changes)
                    if mapped is not None:original_calls[mapped].append(row)
            observed=[];expected=[]
            for row in self.observations[base]:
                expected_span=(row.get('expected') or {}).get('span')
                if expected_span and expected_span['path']==source.path:
                    expected.append((expected_span['start_byte'],expected_span['end_byte']))
                position=(row.get('observed') or {}).get('span')
                if not position or position['path']!=source.path:continue
                mapped=_mapped((position['start_byte'],position['end_byte']),changes)
                if mapped in exact:observed.append((row,exact[mapped]))
            inputs=[edit for edit in changes if edit['role'] not in {'semantic_expected','atomic_neutralization'}
                    and edit['before']!=edit['after'] and not any(_inside(e,edit['old']) for e in expected)]
            for call in calls:
                resolved=self._resolve(source,call,assignments,original_calls,changes)
                if not resolved:continue
                names=sorted(set(self.names)&set(resolved['names']))
                if not names:continue
                fn,args=call_parts(call);affected=[]
                for slot,arg in enumerate(args):
                    direct=[edit for edit in inputs if _overlap(edit['new'],_extent(arg))]
                    affected.extend((edit,slot,'direct_argument') for edit in direct)
                    for name in _read_names(source,arg):
                        binding=_binding(assignments,name,call)
                        if binding is not None:
                            affected.extend((edit,slot,'one_local_assignment') for edit in inputs
                                if _overlap(edit['new'],_extent(binding['value'])))
                if not affected:continue
                parts=_chain(source,fn);receiver=parts[0] if parts and len(parts)==2 else None
                for row,actual in observed:
                    basis=None
                    if _inside(_extent(actual),_extent(call)):
                        basis='call_inside_actual'
                    elif call.end_byte<=actual.start_byte and _scope(call)==_scope(actual):
                        reads=_read_names(source,actual)
                        for name in reads:
                            binding=_binding(assignments,name,actual)
                            if binding and _inside(_extent(binding['value']),_extent(call)):
                                basis='assigned_return_read';break
                        if basis is None and receiver:
                            for member in walk(actual):
                                if member.type in ATTRS:
                                    owner,_=attr_parts(member)
                                    receiver_key=_binding_key(assignments,receiver,call)
                                    if source.text(owner)==receiver and receiver_key is not None and receiver_key==_binding_key(assignments,receiver,actual):
                                        basis='same_unrebound_receiver_field';break
                    if basis:
                        for edit,slot,input_basis in affected:
                            witness=dict(issue_names=names,callee=source.text(fn),callee_identity=resolved['identity'],
                                resolution=resolved['basis'],call_span=dict(path=source.path,start_byte=call.start_byte,end_byte=call.end_byte),
                                original_edit_index=edit['index'],input_basis=input_basis,argument_slot=slot,
                                observation_id=row['id'],observation_basis=basis,
                                actual=source.text(actual))
                            if witness not in result['witnesses']:result['witnesses'].append(witness)
            result['feature']=bool(result['witnesses'])
            result['status']='witness' if result['feature'] else 'no_supported_local_witness'
            result['modified_source_sha256']=hashlib.sha256(source.data).hexdigest()
            result['mapped_observations']=len(observed)
        except (KeyError,ValueError,TypeError,IndexError,AttributeError,UnicodeError) as error:
            result.update(status='unknown',unknowns=[str(error)])
        return result


def select(corpus,frontend,candidates,issue,*,budget=16):
    baseline=semantic_selection.select(corpus,candidates,budget=budget)
    analyzer=Analyzer(corpus,frontend,issue);by_id={row['id']:row for row in candidates}
    evidence={row['id']:analyzer.evidence(row) for row in candidates}
    ranking=sorted(baseline['ranking'],key=lambda row:(not evidence[row['id']]['feature'],row['rank']))
    rows=[dict(row,shape_rank=row['rank'],rank=i+1,selected=i<budget,contract_call=evidence[row['id']]) for i,row in enumerate(ranking)]
    return dict(selected=[by_id[row['id']] for row in rows[:budget]],ranking=rows,
        issue_names=analyzer.names,policy=POLICY,policy_sha256=digest(POLICY),
        baseline_policy_sha256=baseline['policy_sha256'],input_count=len(candidates),selected_count=min(len(candidates),budget))
