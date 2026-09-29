"""Group bounded input alternatives in one source observation context.

Groups are local model questions, never behavioral equivalence classes. This
module neither sends requests nor generates or validates any expected value.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json
import re

from anchor_retrieval.syntax import literal
from relation_search import impact_selection, semantic_selection
from relation_search.instrument import _program_edits


POLICY = dict(version='source-context-alternative-groups-v1',
    context='same base test, family, syntax shape, exact source edit footprint, observation ports, and explicit name-change signature',
    members='original shape ranking within context; every offered group has at most four alternatives',
    priority='least-shown context first; source-shape round robin or greedy unshown observation/port coverage',
    impact_exploration='every fourth group uses original shape order among equally served contexts',
    retention='all unshown candidates retained, including unsupported assertion interfaces',
    model_contract='at most one complete expectation revision per group; no behavioral equivalence claim',
    forbidden_inputs=['target labels','oracle cache','runtime outcome','provider','issue text'])


def _sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def _span(span):
    return {k:span[k] for k in ('path','start_byte','end_byte')}


def _name_changes(edits):
    # Local alpha-numbering in the reused shape routine must not turn a direct
    # receiver/callee-name substitution into a literal alternative.
    name = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z')
    changes=[]
    for edit in edits:
        try:
            literal(edit['after'])
            continue
        except ValueError:
            pass
        if (edit['before'] != edit['after'] and name.fullmatch(edit['before'].strip())
                and name.fullmatch(edit['after'].strip())):
            changes.append(dict(span=_span(edit['span']),before=edit['before'],after=edit['after']))
    return changes


def build_catalogue(corpus, frontend, candidates):
    """Reuse existing syntax and impact analyses; keep exact source provenance."""
    candidates = list(candidates)
    if len({c['id'] for c in candidates}) != len(candidates):
        raise ValueError('candidate IDs must be unique')
    clean = [dict(c,edits=_program_edits(c)) for c in candidates]
    baseline = semantic_selection.select(corpus,clean,budget=len(clean))
    impacted = impact_selection.select(corpus,frontend,clean,budget=len(clean))
    impact_by_id = {r['id']:r for r in impacted['ranking']}
    clean_by_id = {c['id']:c for c in clean}
    groups = {}
    information = {}
    for row in baseline['ranking']:
        candidate = clean_by_id[row['id']]
        evidence = impact_by_id[row['id']]['evidence']
        footprint = [dict(span=_span(e['span']),role=e.get('role','input'))
                     for e in sorted(candidate['edits'],key=lambda e:(e['span']['path'],e['span']['start_byte'],e['span']['end_byte']))]
        ports = sorted({(o['observation_id'],o['port_id']) for o in evidence['obligations']})
        descriptor = dict(base_test_id=row['base_test_id'],family=row['family'],shape_id=row['shape_id'],
            footprint=footprint,observation_ports=ports,name_changes=_name_changes(candidate['edits']),
            observation_focus=dict(selected=candidate.get('selected_observation_id'),
                target=candidate.get('oracle',{}).get('target_assertion_id'),
                assertions=sorted(candidate.get('oracle',{}).get('assertion_ids',[])),
                source=candidate.get('relation',{}).get('source_observation_id'),
                sources=sorted(candidate.get('relation',{}).get('source_observation_ids',[]))))
        context_id = _sha(descriptor)
        group = groups.setdefault(context_id,dict(id=context_id,**descriptor,candidate_ids=[]))
        group['candidate_ids'].append(row['id'])
        information[row['id']] = dict(baseline_rank=row['rank'],impact_rank=impact_by_id[row['id']]['rank'],
            context_id=context_id,eligible=evidence['eligible'],normalization_status=row['normalization_status'],
            exact_source_edits=copy.deepcopy(candidate['edits']),imports=copy.deepcopy(candidate.get('imports',[])),
            observations=[dict(observation_id=o['observation_id'],port_id=o['port_id'],edit_index=o['edit_index'],
                               assertion_span=o['assertion_span'],actual_span=o['actual_span'],expected_span=o['expected_span'])
                          for o in evidence['obligations']],
            unknowns=evidence['unknowns'])
    return dict(policy=POLICY,policy_sha256=_sha(POLICY),candidates=copy.deepcopy(candidates),
                contexts=list(groups.values()),candidate_info=information,input_count=len(candidates),
                eligible_count=sum(r['eligible'] for r in information.values()))


def schedule(catalogue, *, budget=16, max_group_size=4, policy='shape', previous=None):
    """Offer up to budget local questions, retaining a persistent unshown queue."""
    if type(budget) is not int or budget<0 or type(max_group_size) is not int or not 1<=max_group_size<=4:
        raise ValueError('budget must be nonnegative and max_group_size must be in 1..4')
    if policy not in {'shape','impact'}:
        raise ValueError('unknown group selection policy')
    previous = previous or {}
    shown = set(previous.get('shown_ids',[]))
    counts = dict(previous.get('context_shown_counts',{}))
    observed = set(previous.get('shown_observation_ids',[]))
    ports = {tuple(pair) for pair in previous.get('shown_observation_ports',[])}
    records = catalogue['candidate_info']
    remaining = {c['id']:[cid for cid in c['candidate_ids'] if cid not in shown and records[cid]['eligible']]
                 for c in catalogue['contexts']}
    context_by_id = {c['id']:c for c in catalogue['contexts']}
    groups=[]
    # Compute a complete hypothetical group schedule as well as the sent prefix.
    # Only selected groups are added to the persisted shown state below.
    temporary_counts=dict(counts)
    temporary_observed=set(observed)
    temporary_ports=set(ports)
    while any(remaining.values()):
        options=[]
        for context_id,ids in remaining.items():
            if not ids:
                continue
            members=ids[:max_group_size]
            group_ports={tuple(p) for p in context_by_id[context_id]['observation_ports']}
            qids={p[0] for p in group_ports}
            options.append(dict(context_id=context_id,candidate_ids=members,
                service_count=temporary_counts.get(context_id,0),
                baseline_rank=min(records[cid]['baseline_rank'] for cid in members),
                new_observation_count=len(qids-temporary_observed),
                new_observation_port_count=len(group_ports-temporary_ports)))
        exploration=policy=='shape' or (len(groups)+1)%4==0
        def priority(row):
            impact=() if exploration else (-row['new_observation_count'],-row['new_observation_port_count'])
            return (row['service_count'],*impact,row['baseline_rank'],row['context_id'])
        chosen=min(options,key=priority)
        context_id=chosen['context_id']
        selected=len(groups)<budget
        chosen.update(id=_sha([context_id,chosen['candidate_ids']]),rank=len(groups)+1,selected=selected,
            selection_reason='shape_exploration' if exploration else 'unshown_observation_impact',
            base_test_id=context_by_id[context_id]['base_test_id'],max_expectation_revisions=1,
            equivalence_claim=False)
        groups.append(chosen)
        remaining[context_id]=remaining[context_id][len(chosen['candidate_ids']):]
        temporary_counts[context_id]=temporary_counts.get(context_id,0)+1
        group_ports={tuple(p) for p in context_by_id[context_id]['observation_ports']}
        temporary_observed.update(p[0] for p in group_ports)
        temporary_ports.update(group_ports)
        if selected:
            shown.update(chosen['candidate_ids'])
            counts[context_id]=counts.get(context_id,0)+1
            observed.update(p[0] for p in group_ports)
            ports.update(group_ports)
    selected=[g for g in groups if g['selected']]
    candidate_ids=[cid for g in selected for cid in g['candidate_ids']]
    all_ids={c['id'] for c in catalogue['candidates']}
    return dict(policy=policy,policy_spec=POLICY,budget_groups=budget,max_group_size=max_group_size,
        groups=groups,selected_groups=selected,selected_candidate_ids=candidate_ids,
        selected_group_count=len(selected),selected_candidate_count=len(candidate_ids),
        pending_ids=sorted(all_ids-shown),
        ineligible_ids=sorted(cid for cid,r in records.items() if not r['eligible']),
        frontier=dict(candidates=copy.deepcopy(catalogue['candidates']),shown_ids=sorted(shown),
            context_shown_counts=counts,shown_observation_ids=sorted(observed),
            shown_observation_ports=sorted(ports)))


def select(corpus, frontend, candidates, *, budget=16, max_group_size=4, policy='shape', previous=None):
    previous=previous or {}
    pool={c['id']:c for c in previous.get('candidates',[])}
    for candidate in candidates:
        if candidate['id'] in pool:
            old=dict(pool[candidate['id']],edits=_program_edits(pool[candidate['id']]))
            new=dict(candidate,edits=_program_edits(candidate))
            if semantic_selection._material(old)!=semantic_selection._material(new):
                raise ValueError('same candidate ID changed source material')
        pool[candidate['id']]=candidate
    catalogue=build_catalogue(corpus,frontend,pool.values())
    return dict(catalogue=catalogue,**schedule(catalogue,budget=budget,max_group_size=max_group_size,
                                               policy=policy,previous=previous))
