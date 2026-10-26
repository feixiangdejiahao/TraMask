"""Construct source actions by unifying an observation's indexed address.

This experiment starts from source observation dependencies, not an existing
candidate pool. A source writer is instantiated on the observed receiver and
key before that read's source statement. It does not infer an expected value,
prove effects, or establish applicability of any retained assertion.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import islice
import hashlib
import json

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, Source, call_parts, child, walk
from prototypes import state_regions as regions
from prototypes.test_action_and_oracle_transfer import state_contexts as state
from generic_composition.corpus import span
from relational_gap import state_cells as cells

VERSION = 'observation-address-unification.v1'
LIMITATIONS = [
    'source receiver versions and address substitutions are not runtime heap identity or effect proofs',
    'method summaries describe current source; missing effects remain unknown, never evidence that no gap exists',
    'all original assertions are retained; their applicability after the new action is unknown',
    'no source-written value is promoted to an expected result; semantic admission and native execution remain required',
    'intervening opaque calls, later overwrites and external aliases can change whether a syntactic write influences the read',
]


@dataclass(frozen=True)
class JoinBudget:
    max_candidates: int = 16
    max_attempts: int = 128
    max_actions_per_group: int = 32


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def _pos(value):
    at=value.get('span',value)
    return at['path'],at['start_byte'],at['end_byte']


def _inside(inner,outer):
    return inner['path']==outer['path'] and outer['start_byte']<=inner['start_byte']<=inner['end_byte']<=outer['end_byte']


def _simple_root(unit,capsules):
    allowed=[q['assertion_span'] for q in capsules if q.get('assertion_span')]
    if unit.decorators or unit.node.type in {'async_function_definition'} or any(n.type=='async' for n in unit.node.children):
        return False
    forbidden=state._CONTROL|state._NESTED|{'await','await_expression','yield','yield_expression','import_statement','import_from_statement','type_switch_statement','match_statement','goto_statement','labeled_statement'}
    for node in walk(unit.body):
        if node.type in state._NESTED or (node.type in forbidden and not any(_inside(span(unit.source,node),at) for at in allowed)):
            return False
        if node.type=='unary_expression' and unit.source.text(child(node,'operator'))=='&':
            operand=child(node,'operand','argument')
            if operand is not None and operand.type=='identifier':
                return False
    return True


def _resolved(call):
    targets=call.get('targets',[])
    if len(targets)!=1 or not targets[0].get('resolved'):
        raise state.Unsupported('call_target_not_uniquely_resolved')
    if call.get('contexts') or not call.get('receiver') or call['receiver'].get('kind')!='identifier':
        raise state.Unsupported('call_receiver_or_control_unknown')
    return targets[0]['function_id']


def _argument(call,effect):
    key=effect.get('key')
    if key is None:
        raise state.Unsupported('indexed_address_required')
    if key['kind']=='literal':
        return dict(text=key['text'],span=effect['key_span'],literal_known=True,literal_value=key['value'],literal_kind=key.get('literal_kind'),kind='summary_literal',slot=None)
    bindings=[b for b in call.get('argument_bindings',[]) if b.get('function_id')==_resolved(call)
              and b.get('parameter')==key['name'] and b.get('binding_status')=='direct_actual_formal']
    if len(bindings)!=1:
        raise state.Unsupported('key_actual_formal_not_unique')
    actuals=[a for a in call['arguments'] if a['slot']==bindings[0]['slot'] and not a.get('spread')]
    if len(actuals)!=1:
        raise state.Unsupported('key_actual_not_unique')
    return actuals[0]


def _known_key(test,index,actual):
    if actual.get('kind')!='summary_literal':
        at=actual['span']
        if at['path']!=test.source.path or test.source.data[at['start_byte']:at['end_byte']].decode()!=actual['text']:
            raise state.Unsupported('key_source_bytes_mismatch')
    if actual.get('literal_known'):
        value=actual['literal_value']
    else:
        node=test.nodes.get((actual['span']['start_byte'],actual['span']['end_byte']))
        if node is None or node.type!='identifier':
            raise state.Unsupported('key_not_closed_primitive')
        value,_=state._constant(test.source,node,test.snapshots[index])
    if type(value) not in {str,int,bool,type(None)}:
        raise state.Unsupported('key_not_closed_primitive')
    return value


def _key_kind(test,index,actual,value):
    if actual.get('literal_kind'):
        return actual['literal_kind']
    text=actual['text'];node=test.nodes.get((actual['span']['start_byte'],actual['span']['end_byte']))
    environment=test.snapshots[index];seen=set()
    while node is not None and node.type=='identifier':
        binding=environment.get(test.source.text(node))
        if binding is None or binding in seen or binding.kind!='literal' or binding.expression is None:
            break
        seen.add(binding);node=binding.expression;text=test.source.text(node)
        environment=test.snapshots[binding.statement]
    if value is None:
        return text
    return 'go_rune' if test.source.language=='go' and text.startswith("'") else type(value).__name__


def _same_value(a,b):
    return type(a) is type(b) and a==b


def _collect(corpus,index,skipped):
    """Reuse the baseline action bank and its deterministic source order."""
    capsules=defaultdict(list);groups=defaultdict(list)
    for q in corpus.get('capsules',[]):
        if q.get('assertion_span'):
            capsules[q['test_id']].append(q)
    for record in sorted(corpus['tests'].values(),key=cells._rank):
        unit=index.units.get(record['id'])
        if unit is None or not record.get('enclosing_scope_span') or not capsules[record['id']]:
            skipped['source_test_or_observation_unavailable']+=1;continue
        if record.get('parameterization_status','none_detected')!='none_detected' or not _simple_root(unit,capsules[record['id']]):
            skipped['test_scope_not_straight_line']+=1;continue
        for region in regions._regions(unit,record,capsules[record['id']]):
            if region.context:
                skipped['nested_region_unknown']+=1;continue
            local=[q for q in capsules[record['id']] if any(_inside(q['assertion_span'],span(unit.source,s)) for s in region.statements)]
            try:
                test=regions._region_test(index,region,local)
                for original in local:
                    q=cells._phase_capsule(test,original)
                    for insertion,receiver,binding in state._observations(test,q):
                        scope=record['enclosing_scope_span']
                        key=(unit.source.path,scope['start_byte'],scope['end_byte'],binding.producer)
                        groups[key].append((region,test,q,insertion,receiver,binding))
            except state.Unsupported as error:
                skipped[str(error)]+=1
    return groups


def _demands(recipient,frontend_calls,summary,skipped):
    region,test,q,_,_,root=recipient
    traces=[q['observed']['span'],*q.get('observation_value_sources',[])]
    for call in frontend_calls.get(region.parent['id'],[]):
        if not any(_inside(call['span'],trace) for trace in traces):
            continue
        try:
            function_id=_resolved(call)
            statement=state._statement(test,call['span']['start_byte'],call['span']['end_byte'])
            if statement is None:
                raise state.Unsupported('read_phase_missing')
            receiver=call['receiver']['text'];binding=test.snapshots[statement].get(receiver)
            if binding is None or binding.kind!='receiver' or binding.origin!=root.origin:
                raise state.Unsupported('read_receiver_definition_mismatch')
            result=summary(function_id)
            if result.get('status')=='unknown':
                raise state.Unsupported('read_summary_unknown')
            for effect in result.get('reads',[]):
                if effect.get('key') is None:
                    continue
                actual=_argument(call,effect);value=_known_key(test,statement,actual)
                yield dict(recipient=(region,test,q,statement,receiver,binding),call=call,effect=effect,key_actual=actual,key_value=value,key_kind=_key_kind(test,statement,actual,value))
        except (state.Unsupported,KeyError,TypeError) as error:
            skipped[str(error) if isinstance(error,state.Unsupported) else 'read_metadata_unknown']+=1


def _action_call(action,calls_by_position):
    _,test,operation,_=action
    expression=operation.get('expression',test.statements[operation['statement']])
    node=expression.named_children[0] if expression.type=='expression_statement' and len(expression.named_children)==1 else expression
    if node.type not in CALLS or sum(n.type in CALLS for n in walk(node))!=1:
        raise state.Unsupported('action_not_one_direct_call')
    call=calls_by_position.get(_pos(span(test.source,node)))
    if call is None:
        raise state.Unsupported('action_source_call_missing')
    _resolved(call)
    return call


def _render(index,demand,action,identifier,substitution=None):
    region,recipient,_,insertion,receiver,_=demand['recipient']
    donor_region,donor,operation,_=action
    regions._external_declarations_match(donor_region,region,[operation])
    if any(not regions._builtin_available(index,region,recipient,name) for name in operation.get('builtin_names',())):
        raise state.Unsupported('rhs_builtin_shadowed_at_target')
    if any(regions._external_shadowed(index,region,recipient,name) for name in operation['external_names']):
        raise state.Unsupported('external_callee_shadowed_at_target')
    text,operation_spans,_,_,_=regions._render(donor,[operation],recipient,insertion,receiver,identifier)
    position=recipient.statements[insertion].start_byte
    change=None
    if substitution is not None:
        # The shared renderer changes identifiers but preserves direct call
        # structure. Recover that one emitted call by its exact operation span.
        raw=recipient.source.data
        changed=Source(recipient.source.path,(raw[:position]+text.encode()+raw[position:]).decode(),recipient.source.language)
        operation_span=dict(path=recipient.source.path,**operation_spans[0])
        calls=[n for n in walk(changed.root) if n.type in CALLS and _inside(span(changed,n),operation_span)]
        if len(calls)!=1:
            raise state.Unsupported('rendered_action_call_not_unique')
        _,arguments=call_parts(calls[0]);arguments=[a for a in arguments if a.type!='comment']
        if substitution['argument_slot']>=len(arguments):
            raise state.Unsupported('rendered_actual_slot_missing')
        node=arguments[substitution['argument_slot']]
        node=child(node,'value') if node.type=='keyword_argument' else node
        start,end=node.start_byte-position,node.end_byte-position
        before=text.encode()[start:end].decode();replacement=substitution['after']
        text=(text.encode()[:start]+replacement.encode()+text.encode()[end:]).decode()
        change=dict(rendered_before=before,after=replacement,insert_relative_start=start,insert_relative_end=end)
    cells._validate_render(recipient.source,position,text)
    return dict(span=dict(span(recipient.source,recipient.statements[insertion]),end_byte=position),before='',after=text,role='observation_address_action'),change


def generate(corpus,frontend,*,mode='address',budget=None):
    """Generate from Q-address demands; no pre-generated candidates are read."""
    from prototypes.observation_address_effects import summarize_method
    budget=budget or JoinBudget()
    if mode not in {'address','receiver_only'} or any(type(v) is not int or v<1 for v in asdict(budget).values()):
        raise ValueError('invalid mode or positive budget')
    skipped=Counter();candidates=[];attempts=0;seen=set();summaries={};schedule=[];banks=[]
    sources=[Source(path,row['code'],row.get('language',corpus['language'])) for path,row in sorted(corpus['sources'].items())
             if row.get('complete_file',True) and not row.get('parse_error')]
    index=Index(sources,'')
    def summary(function_id):
        if function_id not in summaries:summaries[function_id]=summarize_method(index,function_id)
        return summaries[function_id]
    frontend_calls=defaultdict(list);calls_by_position={}
    for call in frontend.get('calls',[]):
        frontend_calls[call['test_id']].append(call);calls_by_position[_pos(call)]=call
    groups=_collect(corpus,index,skipped);plans=defaultdict(list)
    for key,recipients in groups.items():
        actions=cells._action_bank(recipients,index,budget.max_actions_per_group,skipped)
        banks.append(dict(group=key,actions=[cells._action_key(a) for a in actions]))
        for recipient in recipients:
            for demand in _demands(recipient,frontend_calls,summary,skipped):
                plans[recipient[0].parent['id']].append((demand,actions))
    def actions_for(demand,actions):
        for action in actions:yield demand,action
    def pairs(rows):
        yield from cells._round_robin(actions_for(demand,actions) for demand,actions in rows)
    def pair_identity(demand,action):
        return dict(q=demand['recipient'][2]['id'],read_call=demand['call']['id'],read_effect=demand['effect']['address_span'],action=cells._action_key(action))
    preprocessing_skipped=dict(skipped)
    pair_skipped=Counter()
    order=sorted(plans,key=lambda tid:cells._rank(corpus['tests'][tid]))
    planned=list(islice(cells._round_robin(pairs(plans[tid]) for tid in order),budget.max_attempts))
    planned_schedule=[pair_identity(demand,action) for demand,action in planned]
    for demand,action in planned:
        if attempts>=budget.max_attempts or len(candidates)>=budget.max_candidates:break
        attempts+=1
        recipient=demand['recipient'];region,test,q,insertion,receiver,binding=recipient
        pair=pair_identity(demand,action)
        schedule.append(pair)
        try:
            call=_action_call(action,calls_by_position);writer_summary=summary(_resolved(call))
            writes=writer_summary.get('writes',[]);matched=[];substitution=None
            if mode=='address':
                if writer_summary.get('status')=='unknown':raise state.Unsupported('write_summary_unknown')
                matched=[effect for effect in writes if effect.get('owner_key')==demand['effect'].get('owner_key')
                         and effect.get('field')==demand['effect'].get('field') and effect.get('key') is not None]
                if len(matched)!=1:raise state.Unsupported('write_address_missing_or_ambiguous')
                write=matched[0];actual=_argument(call,write)
                old_value=_known_key(action[1],action[2]['statement'],actual)
                if write['key']['kind']=='literal':
                    if not _same_value(old_value,demand['key_value']) or _key_kind(action[1],action[2]['statement'],actual,old_value)!=demand['key_kind']:raise state.Unsupported('fixed_write_key_mismatch')
                else:
                    # Closed literal actuals avoid dropping evaluations or
                    # introducing unused Go declarations from removed aliases.
                    if not actual.get('literal_known'):raise state.Unsupported('write_actual_not_direct_literal')
                    substitution=dict(argument_slot=actual['slot'],formal=write['key']['name'],before=actual['text'],
                        after=demand['key_actual']['text'],source_actual=actual['span'],demand_actual=demand['key_actual']['span'],
                        old_value=old_value,new_value=demand['key_value'])
            identifier=_hash([VERSION,pair])[:24]
            edit,render_change=_render(index,demand,action,identifier,substitution)
            fingerprint=_hash([region.parent['id'],edit])
            if fingerprint in seen:skipped['duplicate_rendered_candidate']+=1;pair_skipped['duplicate_rendered_candidate']+=1;continue
            seen.add(fingerprint)
            candidate_id='address_'+fingerprint[:24]
            candidates.append(dict(id=candidate_id,base_test_id=region.parent['id'],source_test_ids=sorted({region.parent['id'],action[0].parent['id']}),
                language=corpus['language'],kind='observation_address_join',operator=VERSION,imports=[],edits=[edit],
                target_capsule_id=q['id'],source_observation_id=q['id'],
                oracle=dict(mode='retain_all',applicability='unknown_requires_independent_semantic_review'),
                relation=dict(domain=VERSION,mode=mode,applicability='unknown',effect='source_address_connection_not_runtime_influence_proof'),
                provenance=dict(read_call=demand['call']['span'],read_effect=demand['effect'],write_call=call['span'],write_effects=matched if mode=='address' else writes,
                    receiver_substitution=dict(source=call['receiver']['text'],target=receiver,target_origin=binding.origin,source_origin=action[3]),
                    key_substitution=substitution,rendered_key_edit=render_change,observation=q['assertion_span'],
                    insertion_statement=span(test.source,test.statements[insertion]),source_action=span(action[1].source,action[1].statements[action[2]['statement']]),
                    assertions_edited=False,expected_values_inferred=False,unproved=LIMITATIONS),
                selection=dict(schedule='source_parent_then_observation_then_action_round_robin')))
        except (state.Unsupported,KeyError,TypeError,ValueError) as error:
            reason=str(error) if isinstance(error,state.Unsupported) else 'source_or_render_metadata_unknown'
            skipped[reason]+=1;pair_skipped[reason]+=1
    return dict(version=VERSION,mode=mode,candidates=candidates,attempts=attempts,skipped=dict(sorted(skipped.items())),
        preprocessing_skipped=preprocessing_skipped,pair_skipped=dict(pair_skipped),
        budget=asdict(budget),budget_exhausted=attempts>=budget.max_attempts or len(candidates)>=budget.max_candidates,
        action_bank_sha256=_hash(banks),action_bank_count=sum(len(b['actions']) for b in banks),demand_count=sum(len(p) for p in plans.values()),
        pair_schedule_sha256=_hash(planned_schedule),scheduled_pair_count=len(planned_schedule),scheduled_pairs=planned_schedule,
        attempted_pair_schedule_sha256=_hash(schedule),attempted_pairs=schedule,summary_count=len(summaries),limitations=LIMITATIONS,
        provider_calls=0,native_executions=0,semantic_validity='unassessed')
