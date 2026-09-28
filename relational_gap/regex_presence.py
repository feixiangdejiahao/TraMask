"""Transport an optional source-regex capture into an otherwise fixed input.

The donor supplies the optional unit's exact text. Regex syntax identifies its
capture and literal/finite-separator frame. A bounded worker proves a unique
insertion position by rematching, without executing any subject code.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import json
import subprocess
import sys

from anchor_retrieval.syntax import Source
from generic_composition.corpus import source_text
from generic_composition.engine import stable_id
from .embedded_relations import format_source_string
from .regex_cells import _SourceFacts, _patterns, _flow, _proximity, _finite, _row_edits, _position
from .sequence_cells import _observers
from .structured_ports import carrier_ports, structural_slot_key


@dataclass(frozen=True)
class RegexPresenceBudget:
    max_candidates: int = 128
    max_patterns: int = 32
    max_pattern_bytes: int = 2048
    max_input_bytes: int = 2048
    max_inputs_per_slot: int = 32
    max_groups: int = 24
    max_coordinates: int = 12
    max_attempts: int = 256
    max_match_batches: int = 64
    max_depth: int = 4
    max_ast_nodes: int = 512
    max_presence_units: int = 24
    max_anchor_positions: int = 2049
    max_proposals_per_batch: int = 64
    max_observations: int = 2
    worker_timeout_ms: int = 1200
    allow_proximity: bool = True

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key == 'allow_proximity':
                if type(value) is not bool:
                    raise ValueError('Regex presence proximity flag must be boolean')
            elif type(value) is not int or value < 1:
                raise ValueError('Regex presence budgets must be positive integers')


_WORKER = r'''
import json, re, sys
from collections import Counter, deque
from re import _parser as P, _constants as C, _compiler as K
p=json.load(sys.stdin); limits=p['limits']; skipped=Counter(); attempts=0; checks=0
try:
 original=re.compile(p['pattern'],p['flags'])
 if original.groups>limits['max_groups']: raise ValueError('capture_group_budget')
 tree=P.parse(p['pattern'],p['flags']); state=tree.state
 ancestors={}; group_nodes={}; units=[]; node_count=0
 REPEATS={C.MAX_REPEAT,C.MIN_REPEAT,C.POSSESSIVE_REPEAT}
 def children(op,arg):
  if op is C.SUBPATTERN: return [arg[3]]
  if op is C.BRANCH: return list(arg[1])
  if op in REPEATS: return [arg[2]]
  if op in {C.ASSERT,C.ASSERT_NOT}: return [arg[1]]
  if op is C.ATOMIC_GROUP: return [arg]
  if op is C.GROUPREF_EXISTS: return [x for x in arg[1:] if x is not None]
  return []
 def captures(items):
  out=set()
  for op,arg in items:
   if op is C.SUBPATTERN and arg[0]: out.add(arg[0])
   for sub in children(op,arg): out.update(captures(sub))
  return out
 def inventory(items,parents=()):
  global node_count
  for op,arg in items:
   node_count+=1
   if node_count>limits['max_ast_nodes']: raise ValueError('regex_ast_budget')
   nested=parents
   if op is C.SUBPATTERN and arg[0]:
    ancestors[arg[0]]=list(parents); group_nodes[arg[0]]=arg[3]; nested=parents+(arg[0],)
   for sub in children(op,arg): inventory(sub,nested)
 inventory(tree)
 def frame(items,leaf):
  # Outside the transferred capture, only regex-owned separator syntax is
  # accepted. Broad data classes/dots/backreferences are not separator facts.
  for op,arg in items:
   if op in {C.LITERAL,C.AT}: continue
   if op is C.IN:
    if not all(a is C.LITERAL or a is C.CATEGORY and b in {C.CATEGORY_SPACE,C.CATEGORY_UNI_SPACE}
               for a,b in arg): return False
   elif op is C.CATEGORY:
    if arg not in {C.CATEGORY_SPACE,C.CATEGORY_UNI_SPACE}: return False
   elif op is C.SUBPATTERN:
    group,_,_,sub=arg
    if group==leaf: continue
    if group and group not in ancestors.get(leaf,[]): return False
    if not frame(sub,leaf): return False
   elif op in REPEATS:
    low,high,sub=arg
    if captures(sub) and high>1: return False
    if not frame(sub,leaf): return False
   elif op is C.BRANCH:
    if not all(frame(sub,leaf) for sub in arg[1]): return False
   elif op is C.ATOMIC_GROUP:
    if not frame(arg,leaf): return False
   else: return False
  return True
 def empty_marker():
  group=state.opengroup(); sub=P.SubPattern(state,[]); state.closegroup(group,sub)
  return group,(C.SUBPATTERN,(group,0,0,sub))
 def instrument(items,path=(),repeated=False,asserted=False):
  result=[]
  for index,(op,arg) in enumerate(list(items.data)):
   here=path+(index,)
   optional=None
   if op in REPEATS and arg[0]==0 and arg[1]==1: optional=arg[2]
   elif op is C.BRANCH and len(arg[1])==2:
    empty=[sub for sub in arg[1] if not sub.data]
    nonempty=[sub for sub in arg[1] if sub.data]
    if len(empty)==1 and len(nonempty)==1: optional=nonempty[0]
   descriptor=None
   if optional is not None:
    groups=captures(optional)
    leaves=[g for g in groups if not any(g in ancestors.get(other,[]) for other in groups if other!=g)]
    if groups:
     reason=None
     if repeated: reason='optional_under_repeated_ancestor'
     elif asserted: reason='optional_under_lookaround'
     elif len(leaves)!=1: reason='optional_has_multiple_capture_coordinates'
     elif not frame(optional,leaves[0]): reason='optional_uncaptured_frame_not_structural'
     elif len(units)>=limits['max_presence_units']: reason='optional_unit_budget'
     if reason: skipped[reason]+=1
     else:
      first,left=empty_marker(); last,right=empty_marker()
      descriptor={'id':len(units),'ast_path':list(here),'group':leaves[0],
                  'capture_family':sorted(groups),'ancestors':ancestors.get(leaves[0],[]),
                  'start_marker':first,'end_marker':last,'syntax':str(op),
                  'frame_basis':'regex_literals_finite_literal_classes_or_whitespace'}
      units.append(descriptor)
   for n,sub in enumerate(children(op,arg)):
    instrument(sub,here+(n,),repeated or op in REPEATS and arg[1]>1,
               asserted or op in {C.ASSERT,C.ASSERT_NOT})
   if descriptor: result.append(left)
   result.append((op,arg))
   if descriptor: result.append(right)
  items.data=result
 instrument(tree)
 marked=K.compile(tree,p['flags'])
 def info(match):
  if match is None:return None
  return {'span':list(match.span()),'groups':[match.group(i) for i in range(1,original.groups+1)],
          'spans':[list(match.span(i)) for i in range(1,original.groups+1)]}
 matches=[]
 for text in p['inputs']:
  plain=getattr(original,p['method'])(text); marked_match=getattr(marked,p['method'])(text)
  if info(plain)!=info(marked_match): raise ValueError('marker_instrumentation_changed_original_match')
  matches.append(marked_match)
 def same(before,after,unit,donor,unit_span,at,fragment):
  if after is None:return False
  old=info(before); new=info(after); delta=len(fragment); group=unit['group']
  if new['span']!=[old['span'][0],old['span'][1]+delta]:return False
  if after.span(unit['start_marker'])!=(at,at) or after.span(unit['end_marker'])!=(at+delta,at+delta):return False
  for g in range(1,original.groups+1):
   a,b=before.span(g); value=before.group(g); updated=after.group(g)
   if g==group or g in unit['ancestors'] and value is None:
    da,db=donor.span(g)
    if da<unit_span[0] or db>unit_span[1] or updated!=donor.group(g):return False
    expected=(at+da-unit_span[0],at+db-unit_span[0])
   elif g in unit['ancestors']:
    if not a<=at<=b:return False
    if updated!=value[:at-a]+fragment+value[at-a:]:return False
    expected=(a,b+delta)
   else:
    if updated!=value:return False
    if a<0:expected=(a,b)
    elif a==b==at:
     if after.span(g) not in {(a,b),(a+delta,b+delta)}:return False
     continue
    elif b<=at:expected=(a,b)
    elif a>=at:expected=(a+delta,b+delta)
    else:return False
   if after.span(g)!=expected:return False
  return True
 proposals=[]; seen=set()
 if len(units)>limits['max_coordinates']:
  skipped['optional_coordinate_budget']+=len(units)-limits['max_coordinates']
 def tasks(base_index,before):
  if before is None:return
  base=p['inputs'][base_index]
  for unit in units[:limits['max_coordinates']]:
   group=unit['group']; start=before.start(unit['start_marker']); end=before.start(unit['end_marker'])
   if before.group(group) is not None:continue
   if start<0 or start!=end:
    skipped['absent_capture_has_no_empty_optional_unit_anchor']+=1;continue
   lo,hi=before.span()
   if hi-lo+1>limits['max_anchor_positions']:
    skipped['optional_anchor_search_budget']+=1;continue
   for donor_index,donor in enumerate(matches):
    if donor is None or donor.group(group) is None:continue
    ds,de=donor.start(unit['start_marker']),donor.start(unit['end_marker'])
    if ds<0 or de<=ds or not ds<=donor.start(group)<=donor.end(group)<=de:
     skipped['donor_optional_unit_not_consuming_capture']+=1;continue
    fragment=p['inputs'][donor_index][ds:de]
    signature=(base_index,unit['id'],fragment,donor.group(group))
    if signature in seen:continue
    seen.add(signature)
    if len((base+fragment).encode())>limits['max_input_bytes']:
     skipped['optional_generated_input_size_budget']+=1;continue
    yield base_index,before,base,unit,group,start,lo,hi,donor_index,donor,ds,de,fragment
 pending=deque(tasks(i,m) for i,m in enumerate(matches))
 while pending and attempts<limits['max_attempts'] and len(proposals)<limits['max_proposals_per_batch']:
  stream=pending.popleft()
  try:task=next(stream)
  except StopIteration:continue
  pending.append(stream)
  base_index,before,base,unit,group,start,lo,hi,donor_index,donor,ds,de,fragment=task
  attempts+=1; valid=[]
  for at in range(lo,hi+1):
   value=base[:at]+fragment+base[at:]
   after=getattr(marked,p['method'])(value);checks+=1
   if same(before,after,unit,donor,(ds,de),at,fragment):
    valid.append((at,value,after))
    if len(valid)>1:break
  if len(valid)>1:
   skipped['optional_insertion_anchor_ambiguous']+=1;continue
  if not valid:
   skipped['optional_insertion_does_not_preserve_other_coordinates']+=1;continue
  at,value,after=valid[0]
  if at!=start:
   skipped['optional_insertion_changes_absent_parse_anchor']+=1;continue
  plain=getattr(original,p['method'])(value)
  if info(plain)!=info(after):raise ValueError('marker_instrumentation_changed_generated_match')
  proposals.append({'base_index':base_index,'donor_index':donor_index,'unit':unit,'group':group,
                    'insertion':at,'fragment':fragment,'donor_unit_span':[ds,de],
                    'donor_capture_span':list(donor.span(group)),'generated':value,
                    'before':info(before),'after':info(after),
                    'anchor_proof':{'valid_positions':1,'examined_domain':[lo,hi],
                                    'all_positions_checked':True,'matches_original_absent_unit_anchor':True}})
 print(json.dumps({'proposals':proposals,'units':units,'names':dict(original.groupindex),
                   'attempts':attempts,'match_checks':checks,'skipped':dict(skipped),
                   'exhausted':attempts>=limits['max_attempts'] or len(proposals)>=limits['max_proposals_per_batch']
                               or any(key.endswith('_budget') for key in skipped)},ensure_ascii=True))
except (ValueError,re.error,OverflowError,RuntimeError,RecursionError,TypeError) as error:
 print(json.dumps({'error':str(error),'proposals':[],'attempts':attempts,'match_checks':checks,'skipped':dict(skipped)}))
'''


def presence_plans(pattern: dict, inputs: list[str], *, budget: RegexPresenceBudget | None = None):
    """Pure source-string witness enumeration in a timeout-bounded worker."""
    budget = budget or RegexPresenceBudget()
    unknown = lambda reason: {'proposals': [], 'units': [], 'attempts': 0, 'skipped': {reason: 1},
                              'exhausted': reason.endswith(('_budget', '_timeout'))}
    if (type(pattern.get('pattern')) is not str or type(pattern.get('flags', 0)) is not int
            or pattern.get('method') not in {'match', 'fullmatch', 'search'}):
        return unknown('optional_pattern_metadata_invalid')
    if len(pattern['pattern'].encode()) > budget.max_pattern_bytes or len(inputs) > budget.max_inputs_per_slot:
        return unknown('optional_pattern_or_input_count_budget')
    if any(type(value) is not str or len(value.encode()) > budget.max_input_bytes for value in inputs):
        return unknown('optional_source_input_size_budget')
    request = {'pattern': pattern['pattern'], 'flags': pattern.get('flags', 0),
               'method': pattern['method'], 'inputs': inputs, 'limits': asdict(budget)}
    try:
        process = subprocess.run([sys.executable, '-I', '-c', _WORKER], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=budget.worker_timeout_ms / 1000)
        result = json.loads(process.stdout)
    except subprocess.TimeoutExpired:
        return unknown('optional_regex_worker_timeout')
    except (OSError, ValueError):
        return unknown('optional_regex_worker_failed')
    if process.returncode or result.get('error'):
        return unknown('optional_regex_unsupported:' + str(result.get('error', 'worker_exit')))
    return result


def generate_regex_presence(corpus, frontend, *, budget: RegexPresenceBudget | None = None):
    budget = budget or RegexPresenceBudget()
    skipped, sources, facts = Counter(), {}, {}
    for path, row in corpus['sources'].items():
        if row.get('language', corpus['language']) != 'python' or row.get('parse_error') or not row.get('complete_file', True):
            continue
        source = Source(path, row['code'], 'python')
        try:
            facts[path] = _SourceFacts(source, frontend.get('functions', []))
        except (SyntaxError, ValueError):
            continue
        sources[path] = source
    for fact in facts.values():
        fact.registry = facts
    patterns = _patterns(facts, budget, skipped)
    enriched = _finite(corpus) if sources else corpus
    tests, capsules, groups = corpus['tests'], defaultdict(list), defaultdict(list)
    for q in corpus.get('capsules', ()):
        if q.get('assertion_span'):
            capsules[q['test_id']].append(q)
    for donor in enriched.get('donors', ()):
        if (donor.get('kind') == 'parameter_row' or donor['test_id'] not in tests
                or donor['span']['path'] not in sources or not capsules[donor['test_id']]
                or donor.get('oracle_dependency') or donor.get('diagnostic')
                or not donor.get('literal_known') or type(donor.get('literal_value')) is not str):
            continue
        if len(donor['literal_value'].encode()) > budget.max_input_bytes:
            skipped['input_size_budget'] += 1
            continue
        if source_text(corpus, donor['span']) != donor['text']:
            continue
        for port in carrier_ports(sources[donor['span']['path']], donor, frontend):
            if not port.get('structural_path'):
                groups[structural_slot_key(port)].append((donor, port))
    calls = {_position(call): call for call in frontend.get('calls', ())}
    context = {'calls': calls, 'functions': {f['id']: f for f in frontend.get('functions', ())},
               'forwarding': defaultdict(list), 'reachable': {}}
    for call in frontend.get('production_calls', ()):
        context['forwarding'][call['function_id']].extend(t['function_id'] for t in call.get('targets', ()))
    bindings = {b['id']: b for b in frontend.get('bindings', ())}
    pool, attempts, batches, worker_exhausted = {}, 0, 0, False
    for pattern in patterns:
        exact = _flow(pattern, frontend, facts, budget)
        for key, available in sorted(groups.items(), key=lambda pair: repr(pair[0])):
            members = []
            for donor, port in available:
                proof = exact.get((_position(port['call_span']), port['argument_slot']))
                other_slot = any(position == _position(port['call_span']) for position, _ in exact)
                if proof is not None or not other_slot and budget.allow_proximity and _proximity(pattern, port, context, budget):
                    members.append((donor, port, proof))
            members.sort(key=lambda row: (row[2] is None, tests[row[0]['test_id']].get('retrieval_rank') or 10**9,
                                          _position(row[0]), row[0]['id']))
            members = members[:budget.max_inputs_per_slot]
            if len({row[0]['literal_value'] for row in members}) < 2:
                continue
            if batches >= budget.max_match_batches or attempts >= budget.max_attempts:
                break
            local_budget = RegexPresenceBudget(**dict(asdict(budget), max_attempts=budget.max_attempts-attempts))
            plans = presence_plans(pattern, [row[0]['literal_value'] for row in members], budget=local_budget)
            batches += 1
            attempts += plans['attempts']
            skipped.update(plans['skipped'])
            worker_exhausted |= plans.get('exhausted', False)
            for plan in plans['proposals']:
                target, port, proof = members[plan['base_index']]
                donor = members[plan['donor_index']][0]
                row_edits, instantiation = _row_edits(corpus, target, facts)
                if row_edits is None:
                    skipped['complete_row_instantiation_unavailable'] += 1
                    continue
                call = calls.get(_position(port['call_span']))
                if call is None:
                    continue
                qs = _observers({'test_id': target['test_id'], 'members': [{'call': call}]}, capsules, bindings, budget)
                if not qs:
                    skipped['optional_following_observation_not_recovered'] += 1
                    continue
                value = plan['generated']
                after = repr(value) if target.get('finite_input') else format_source_string(value, 'python', target['text'])
                if after is None:
                    skipped['optional_source_string_spelling_unsupported'] += 1
                    continue
                edit = {'span': target['span'], 'before': target['text'], 'after': after,
                        'role': 'source_optional_capture_presence'}
                group = plan['group']
                group_name = next((name for name, number in plans['names'].items() if number == group), None)
                for q in qs:
                    identifier = stable_id('regex-presence', target['test_id'], q['id'], [edit, *row_edits])
                    if identifier in pool:
                        continue
                    pool[identifier] = {
                        'id': identifier, 'kind': 'source_regex_optional_presence', 'language': 'python',
                        'base_test_id': target['test_id'], 'source_test_ids': sorted({target['test_id'], donor['test_id']}),
                        'edits': [edit, *row_edits], 'imports': [],
                        'source_observation_id': q['id'], 'target_capsule_id': q['id'],
                        'relation': {'domain': 'source_regex_optional_presence', 'cell': 'absent_to_source_present_capture',
                                     'pattern_id': pattern['id'], 'group': group, 'group_name': group_name,
                                     'before': None, 'after': plan['after']['groups'][group-1],
                                     'input_slot': list(key), 'binding_path': proof or [],
                                     'binding_status': 'source_actual_formal_flow' if proof is not None else 'source_owner_proximity_unresolved',
                                     'optional_unit': plan['unit'], 'parameter_instantiation': instantiation,
                                     'rematch': 'selected_capture_and_ancestors_only; unrelated_values_and_frame_preserved',
                                     'status': 'source_grammar_hypothesis_runtime_unconfirmed'},
                        'oracle': {'mode': 'retain_all', 'source_test_id': target['test_id'], 'assertion_ids': [q['id']],
                                   'basis': None, 'applicability': 'requires_independent_admission'},
                        'provenance': {'source_spans': [pattern['pattern_span'], pattern['declaration_span'], pattern['use_span'],
                                                        target['span'], donor['span'], *(proof or [])],
                                       'pattern': pattern, 'source_donor_ids': [target['id'], donor['id']],
                                       'source_input': target['literal_value'], 'source_presence_input': donor['literal_value'],
                                       'inserted_fragment': plan['fragment'], 'donor_unit_unicode_span': plan['donor_unit_span'],
                                       'donor_capture_unicode_span': plan['donor_capture_span'],
                                       'insertion_unicode_offset': plan['insertion'],
                                       'insertion_utf8_offset': len(target['literal_value'][:plan['insertion']].encode()),
                                       'before_match': plan['before'], 'after_match': plan['after'],
                                       'anchor_proof': plan['anchor_proof'], 'source_observation_span': q['assertion_span'],
                                       'checks': {'donor_optional_unit_reused_exactly': True, 'source_frame_unchanged_by_insertion': True,
                                                  'all_unrelated_capture_values_and_spans_preserved': True,
                                                  'unique_insertion_rematched_with_original_regex': True},
                                       'unproved': ['runtime_parser_reachability', 'capture_semantics', 'oracle_transport']},
                        'selection': {'proof_order': int(proof is None),
                                      'base_retrieval_rank': tests[target['test_id']].get('retrieval_rank'),
                                      'schedule': 'source_input_attempts_then_base_test_candidates_round_robin'},
                    }
        if batches >= budget.max_match_batches or attempts >= budget.max_attempts:
            break
    queues = defaultdict(deque)
    for candidate in sorted(pool.values(), key=lambda c: (c['selection']['proof_order'],
                            c['selection']['base_retrieval_rank'] or 10**9, c['base_test_id'], c['id'])):
        queues[candidate['base_test_id']].append(candidate)
    candidates = []
    while queues and len(candidates) < budget.max_candidates:
        for test_id in list(queues):
            candidates.append(queues[test_id].popleft())
            if not queues[test_id]:
                del queues[test_id]
            if len(candidates) >= budget.max_candidates:
                break
    return {'domain': 'source_regex_optional_presence', 'candidates': candidates, 'patterns': patterns,
            'budget': asdict(budget), 'attempts': attempts, 'skipped': dict(sorted(skipped.items())),
            'budget_exhausted': worker_exhausted or any(key.endswith('_budget') for key in skipped)
                                or attempts >= budget.max_attempts or batches >= budget.max_match_batches or len(pool) > len(candidates),
            'counts': {'patterns': len(patterns), 'match_batches': batches, 'pool': len(pool), 'candidates': len(candidates)},
            'finite_inputs': enriched.get('finite_inputs', {})}
