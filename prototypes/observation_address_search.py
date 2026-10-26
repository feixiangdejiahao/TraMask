"""Demand-directed address search over one source-global closed action bank.

A returned indexed read supplies an address demand. Source method writes are
indexed by declaration owner and field before any demand/action pair budget is
spent. One-way receiver/key substitutions construct the new action; no existing
candidate pool, expected-output inference, or semantic verdict is consumed.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from dataclasses import asdict,dataclass
from itertools import islice
import time

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source
from prototypes import state_regions as regions
from prototypes import observation_address_join as base
from prototypes.observation_address_effects import summarize_method
from prototypes.test_action_and_oracle_transfer import state_contexts as state
from generic_composition.corpus import span
from relational_gap import state_cells as cells

VERSION='source-global-observation-address-search.v2'
@dataclass(frozen=True)
class SearchBudget:
    max_candidates: int = 16
    max_attempts: int = 128


JoinBudget=SearchBudget
LIMITATIONS=base.LIMITATIONS


def _key_actual(call,effect):
    actual=base._argument(call,effect)
    if actual.get('kind')=='summary_literal':
        actual=dict(actual,span=effect['key']['value_span'],address_key_span=effect['key_span'])
    return actual


def _bank(corpus,frontend_calls,index,summary,skipped):
    """Source-owned calls can donate without an observation of their receiver.

    The existing region scanner closes only simple local receivers and literal
    arguments. A later unrelated control statement does not erase an earlier
    closed source action. Branch/closure interiors are never visited here.
    """
    capsules=defaultdict(list)
    for q in corpus.get('capsules',[]):
        if q.get('assertion_span'):capsules[q['test_id']].append(q)
    bank=[];seen=set()
    for record in sorted(corpus['tests'].values(),key=cells._rank):
        unit=index.units.get(record['id'])
        if unit is None or record.get('parameterization_status','none_detected')!='none_detected':
            skipped['donor_scope_unavailable']+=1;continue
        for region in regions._regions(unit,record,capsules[record['id']]):
            if region.context:skipped['donor_nested_region']+=1;continue
            local=[q for q in capsules[record['id']] if any(base._inside(q['assertion_span'],span(unit.source,s)) for s in region.statements)]
            test=regions._region_test(index,region,local)
            for call in frontend_calls.get(record['id'],[]):
                if call['id'] in seen:continue
                at=state._statement(test,call['span']['start_byte'],call['span']['end_byte'])
                if at is None or at in test.assertions:continue
                try:
                    function_id=base._resolved(call);effect_summary=summary(function_id)
                    writes=effect_summary.get('writes',[])
                    if effect_summary.get('status')=='unknown' or not writes:
                        skipped['donor_has_no_supported_write_summary']+=1;continue
                    receiver=call['receiver']['text'];binding=test.snapshots[at].get(receiver)
                    if binding is None or binding.kind!='receiver':
                        raise state.Unsupported('donor_receiver_not_source_local')
                    operation=regions._operation(index,region,test,at,binding.origin)
                    if operation is None:raise state.Unsupported('donor_call_not_closed_operation')
                    action=(region,test,operation,binding.origin)
                    exact=base._action_call(action,{base._pos(call):call})
                    if exact['id']!=call['id']:raise state.Unsupported('donor_call_not_whole_action')
                    owner=tuple(effect_summary['owner_key'])
                    if any(tuple(w['owner_key'])!=owner for w in writes):
                        raise state.Unsupported('donor_write_owner_ambiguous')
                    row=dict(id=call['id'],source_test_id=record['id'],call=call['span'],statement=span(test.source,test.statements[at]),
                        owner_key=owner,fields=sorted({w['field'] for w in writes}),write_effects=writes,
                        receiver_binding_origin=binding.origin)
                    bank.append(dict(row=row,action=action,call=call));seen.add(call['id'])
                except (state.Unsupported,KeyError,TypeError,ValueError) as error:
                    skipped[str(error) if isinstance(error,state.Unsupported) else 'donor_source_metadata_unknown']+=1
    return bank


def _demands(corpus,index,frontend_calls,summary,skipped):
    groups=base._collect(corpus,index,skipped);demands=[];seen=set()
    for recipients in groups.values():
        for recipient in recipients:
            for demand in base._demands(recipient,frontend_calls,summary,skipped):
                actual=_key_actual(demand['call'],demand['effect'])
                demand=dict(demand,key_actual=actual)
                region,_,q,_,receiver,binding=demand['recipient']
                identity=[q['id'],demand['call']['id'],demand['effect']['address_span']]
                identifier=base._hash(identity)[:24]
                if identifier in seen:continue
                seen.add(identifier)
                row=dict(id=identifier,source_test_id=region.parent['id'],observation_id=q['id'],observation=q['assertion_span'],
                    call=demand['call']['span'],call_id=demand['call']['id'],owner_key=demand['effect']['owner_key'],field=demand['effect']['field'],
                    read_effect=demand['effect'],key_actual=actual,receiver=receiver,receiver_binding_origin=binding.origin)
                demands.append(dict(row=row,demand=demand))
    return demands


def generate(corpus,frontend,*,mode='address',budget=None):
    budget=budget or JoinBudget()
    if mode not in {'address','receiver_only'} or any(type(v) is not int or v<1 for v in asdict(budget).values()):
        raise ValueError('invalid mode or positive budget')
    started=time.monotonic();bank_skipped=Counter();demand_skipped=Counter();pair_skipped=Counter()
    sources=[Source(p,r['code'],r.get('language',corpus['language'])) for p,r in sorted(corpus['sources'].items())
             if r.get('complete_file',True) and not r.get('parse_error')]
    index=Index(sources,'');index_done=time.monotonic();summaries={}
    def summary(uid):
        if uid not in summaries:summaries[uid]=summarize_method(index,uid)
        return summaries[uid]
    frontend_calls=defaultdict(list)
    for call in frontend.get('calls',[]):frontend_calls[call['test_id']].append(call)
    bank=_bank(corpus,frontend_calls,index,summary,bank_skipped);bank_done=time.monotonic()
    demands=_demands(corpus,index,frontend_calls,summary,demand_skipped);demand_done=time.monotonic()
    by_owner=defaultdict(list);by_field=defaultdict(list)
    for entry in bank:
        row=entry['row'];owner=tuple(row['owner_key']);by_owner[owner].append(entry)
        for field in row['fields']:by_field[owner,field].append(entry)
    plans=defaultdict(list);queries=[]
    for entry in demands:
        row,demand=entry['row'],entry['demand'];owner=tuple(row['owner_key'])
        hits=by_field[owner,row['field']] if mode=='address' else by_owner[owner]
        retrieved=hits  # Only the global round-robin pair budget limits retrieval.
        queries.append(dict(demand_id=row['id'],lookup_kind='owner_field' if mode=='address' else 'owner',
            owner_key=owner,field=row['field'] if mode=='address' else None,
            all_hit_ids=[a['row']['id'] for a in hits],retrieved_ids=[a['row']['id'] for a in retrieved]))
        plans[row['source_test_id']].append((entry,retrieved))
    def actions_for(entry,actions):
        for action in actions:yield entry,action
    def pairs(rows):
        yield from cells._round_robin(actions_for(entry,actions) for entry,actions in rows)
    order=sorted(plans,key=lambda tid:cells._rank(corpus['tests'][tid]))
    planned=list(islice(cells._round_robin(pairs(plans[tid]) for tid in order),budget.max_attempts))
    def identity(entry,action):return dict(demand_id=entry['row']['id'],donor_bank_id=action['row']['id'])
    schedule=[identity(entry,action) for entry,action in planned]
    preprocessing_done=time.monotonic();candidates=[];seen=set();attempted=[]
    for entry,bank_entry in planned:
        if len(candidates)>=budget.max_candidates:break
        pair=identity(entry,bank_entry);attempted.append(pair)
        demand=entry['demand'];action=bank_entry['action'];call=bank_entry['call'];writes=bank_entry['row']['write_effects']
        region,test,q,insertion,receiver,binding=demand['recipient'];substitution=None;matched=[]
        try:
            if mode=='address':
                matched=[effect for effect in writes if tuple(effect['owner_key'])==tuple(demand['effect']['owner_key'])
                         and effect['field']==demand['effect']['field'] and effect.get('key') is not None]
                if len(matched)!=1:raise state.Unsupported('write_address_missing_or_ambiguous')
                write=matched[0];actual=_key_actual(call,write);old_value=base._known_key(action[1],action[2]['statement'],actual)
                if write['key']['kind']=='literal':
                    if (not base._same_value(old_value,demand['key_value'])
                            or base._key_kind(action[1],action[2]['statement'],actual,old_value)!=demand['key_kind']):
                        raise state.Unsupported('fixed_write_key_mismatch')
                else:
                    if not actual.get('literal_known'):raise state.Unsupported('write_actual_not_direct_literal')
                    substitution=dict(argument_slot=actual['slot'],formal=write['key']['name'],before=actual['text'],after=demand['key_actual']['text'],
                        source_actual=actual['span'],demand_actual=demand['key_actual']['span'],old_value=old_value,new_value=demand['key_value'])
            identifier=base._hash([VERSION,pair])[:24]
            edit,render_change=base._render(index,demand,action,identifier,substitution)
            fingerprint=base._hash([region.parent['id'],edit])
            if fingerprint in seen:raise state.Unsupported('duplicate_rendered_candidate')
            seen.add(fingerprint)
            candidates.append(dict(id='address_'+fingerprint[:24],base_test_id=region.parent['id'],source_test_ids=sorted({region.parent['id'],action[0].parent['id']}),
                language=corpus['language'],kind='observation_address_search',operator=VERSION,imports=[],edits=[edit],
                target_capsule_id=q['id'],source_observation_id=q['id'],oracle=dict(mode='retain_all',applicability='unknown_requires_independent_semantic_review'),
                relation=dict(domain=VERSION,mode=mode,applicability='unknown',effect='source_address_connection_not_runtime_influence_proof'),
                provenance=dict(read_call=demand['call']['span'],read_effect=demand['effect'],write_call=call['span'],write_effects=matched if mode=='address' else writes,
                    donor_bank_id=bank_entry['row']['id'],demand_id=entry['row']['id'],lookup_before_pair_budget=True,
                    receiver_substitution=dict(source=call['receiver']['text'],target=receiver,target_origin=binding.origin,source_origin=action[3]),
                    key_substitution=substitution,rendered_key_edit=render_change,observation=q['assertion_span'],
                    insertion_statement=span(test.source,test.statements[insertion]),source_action=bank_entry['row']['statement'],
                    assertions_edited=False,expected_values_inferred=False,unproved=LIMITATIONS),
                selection=dict(schedule='parent_then_demand_then_indexed_source_action_round_robin')))
        except (state.Unsupported,KeyError,TypeError,ValueError) as error:
            pair_skipped[str(error) if isinstance(error,state.Unsupported) else 'source_or_render_metadata_unknown']+=1
    finished=time.monotonic();bank_rows=[a['row'] for a in bank];demand_rows=[d['row'] for d in demands]
    return dict(version=VERSION,mode=mode,candidates=candidates,attempts=len(attempted),budget=asdict(budget),
        budget_exhausted=len(candidates)>=budget.max_candidates or len(attempted)>=budget.max_attempts,
        full_source_bank=bank_rows,full_source_bank_sha256=base._hash(bank_rows),full_source_bank_count=len(bank_rows),
        demand_rows=demand_rows,demand_population_sha256=base._hash(demand_rows),indexed_demand_count=len(demand_rows),
        queries=queries,query_count=len(queries),raw_retrieved_count=sum(len(q['all_hit_ids']) for q in queries),
        retrieved_count=sum(len(q['retrieved_ids']) for q in queries),
        scheduled_pairs=schedule,pair_schedule_sha256=base._hash(schedule),scheduled_pair_count=len(schedule),
        attempted_pairs=attempted,attempted_pair_schedule_sha256=base._hash(attempted),
        bank_skipped=dict(bank_skipped),demand_skipped=dict(demand_skipped),pair_skipped=dict(pair_skipped),
        timings=dict(index_seconds=index_done-started,bank_seconds=bank_done-index_done,demand_seconds=demand_done-bank_done,
            preprocessing_seconds=preprocessing_done-started,search_seconds=finished-preprocessing_done,total_seconds=finished-started),
        summary_count=len(summaries),limitations=LIMITATIONS,provider_calls=0,native_executions=0,semantic_validity='unassessed')
