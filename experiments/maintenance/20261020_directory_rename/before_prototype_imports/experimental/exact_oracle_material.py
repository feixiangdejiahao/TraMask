"""Conservative, source-exact duplicate accounting for oracle input budgets.

This is not semantic equivalence and is not connected to a live selector.
Canonical source programs are compared separately from the stronger request
material identity. Generated test registration names and scheduling provenance
are outside this identity; source bytes containing those names are not erased.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json

from experimental.singleton_oracle_slots import assertion_inventory
from relation_search.instrument import _program_edits

VERSION = 'exact-oracle-material-v1'
# Reviewed consumers: oracle.prepare_requests / singleton expected slots,
# oracle_evidence.build_evidence, emitter.emit and instrument._program_edits.
# These fields describe derivation/ranking/admission rather than material read
# by those consumers. Unknown fields remain part of the conservative key.
IGNORED_METADATA = frozenset('''id kind operator generator relation oracle
oracle_revision_sites oracle_status parent_candidate_id parent_candidate_ids
static_parent_id ablation ablation_parent_id focus_test_id target_capsule_id
priority provenance selection source_provenance static_novelty arg_values
source_observation_id source_window source_retrieval_rank search_shape
source_constraint_derivations source_evidence source_sha256 equivalence_key
equivalent_candidates'''.split())
RUNTIME_FIELDS = frozenset('''runtime_probes control_runtime_probes
runtime_profile_limitations instrumentation source_profile_ids is_source_profile
execution_lane helper_files extra_setup setup controls control_setup'''.split())
HANDLED_FIELDS = frozenset('''base_test_id language edits program_edits imports
source_test_ids source_contexts impact_evidence'''.split()) | RUNTIME_FIELDS
POLICY = dict(version=VERSION, same_scope='case + full corpus/frontend identities',
    program='same base test and byte-identical canonical modified owner',
    material_components=['edits', 'imports', 'assertions', 'source_controls',
                         'source_contexts', 'runtime_context', 'impact_obligations', 'unknown_fields'],
    ignored_metadata=sorted(IGNORED_METADATA), preserve_array_order=True,
    selection='keep first representative in frozen eligible order; refill budget',
    unmaterializable='unique candidate; never merge',
    scope='dependency-mode oracle material, not an emitted-runtime equivalence theorem')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def sha(value):
    data = value if isinstance(value, bytes) else value.encode() if isinstance(value, str) else canonical(value).encode()
    return hashlib.sha256(data).hexdigest()


class MaterialIndex:
    def __init__(self, case, corpus, frontend):
        self.case, self.corpus, self.frontend = case, corpus, frontend
        self.scope = dict(case=case, corpus_sha256=sha(corpus), frontend_sha256=sha(frontend))
        self.observations = defaultdict(list)
        for row in frontend.get('observations', []):
            self.observations[row.get('test_id')].append(row)
        self._programs = {}

    def _program(self, candidate, edits):
        base = candidate['base_test_id']
        key = sha([base, edits])
        if key in self._programs:
            return self._programs[key]
        test = self.corpus['tests'][base]
        extent = test['span']
        path = extent['path']
        original = self.corpus['sources'][path]['code'].encode()
        ordered = sorted(edits, key=lambda row: (row['span']['start_byte'], row['span']['end_byte']))
        previous = None
        for edit in ordered:
            span = edit['span']
            start, end = span['start_byte'], span['end_byte']
            if span['path'] != path or not extent['start_byte'] <= start <= end <= extent['end_byte']:
                raise ValueError('edit_outside_selected_test')
            if previous is not None and (previous[1] > start or previous[0] == previous[1] == start):
                raise ValueError('overlapping_or_ambiguous_insertions')
            if original[start:end].decode() != edit['before']:
                raise ValueError('original_source_edit_mismatch')
            previous = (start, end)
        data = original
        for edit in reversed(ordered):
            span = edit['span']
            data = data[:span['start_byte']] + edit['after'].encode() + data[span['end_byte']:]
        assertions = assertion_inventory(self.corpus, {'observations':self.observations[base]},
                                         dict(candidate, edits=edits))
        identity = dict(scope=self.scope, base_test_id=base, path=path,
            language=self.corpus['language'], original_owner_sha256=sha(original),
            modified_owner_sha256=sha(data), modified_owner_bytes=len(data))
        self._programs[key] = identity, assertions
        return identity, assertions

    def record(self, candidate, *, impact_evidence=None):
        identifier = candidate['id']
        try:
            edits = _program_edits(candidate)
            program, assertions = self._program(candidate, edits)
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            unique = sha([self.scope, identifier, candidate])
            return dict(id=identifier, status='unmaterializable', reason=str(error),
                        program_key=unique, material_key=unique, components={})
        evidence = candidate.get('impact_evidence', {}) if impact_evidence is None else impact_evidence
        components = dict(edits=edits, imports=candidate.get('imports', []),
            assertions=assertions, source_controls=candidate.get('source_test_ids', []),
            source_contexts=candidate.get('source_contexts', []),
            runtime_context={key:candidate[key] for key in sorted(RUNTIME_FIELDS) if key in candidate},
            impact_obligations=evidence.get('obligations', []),
            unknown_fields={key:value for key,value in candidate.items()
                            if key not in IGNORED_METADATA | HANDLED_FIELDS})
        program_key = sha(program)
        hashes = {name:sha(value) for name,value in components.items()}
        return dict(id=identifier, status='materialized', program_key=program_key,
            material_key=sha([program_key, hashes]), components=hashes,
            owner=program, assertion_count=len(assertions),
            editable_assertion_count=sum(row['editable'] for row in assertions),
            unknown_field_names=sorted(components['unknown_fields']))


def summarize(records):
    """Each split count is conditional on exact full-owner program identity.

    Component counts are intentionally not additive: multiple constraints may
    distinguish the same pair. Removing one component is a boundary census,
    never authorization to use a looser selection rule.
    """
    records = list(records)
    programs = defaultdict(list)
    materials = defaultdict(list)
    for row in records:
        programs[row['program_key']].append(row)
        materials[row['material_key']].append(row['id'])
    material_count = len(materials)
    constraints = {}
    for component in POLICY['material_components']:
        split = [group for group in programs.values()
                 if len({row['components'].get(component) for row in group}) > 1]
        without = {(row['program_key'], canonical({k:v for k,v in row['components'].items() if k != component}))
                   for row in records}
        constraints[component] = dict(program_classes_split=len(split),
            candidates_in_split_classes=sum(map(len,split)),
            additional_classes_over_program=sum(len({r['components'].get(component) for r in g})-1 for g in programs.values()),
            conservative_classes_released_if_omitted=material_count-len(without))
    return dict(candidate_count=len(records), program_classes=len(programs),
        material_classes=material_count, redundant_program_slots=len(records)-len(programs),
        redundant_material_slots=len(records)-material_count,
        unmaterializable=sum(row['status'] != 'materialized' for row in records),
        duplicate_material_groups=[ids for ids in materials.values() if len(ids)>1],
        constraints=constraints)


def select_unique(ordered_records, budget=16):
    if type(budget) is not int or budget < 0:
        raise ValueError('budget must be a nonnegative integer')
    selected, seen, skipped = [], set(), []
    for row in ordered_records:
        if len(selected) >= budget:
            break
        if row['material_key'] in seen:
            skipped.append(row['id'])
            continue
        seen.add(row['material_key'])
        selected.append(row)
    return dict(selected=selected, skipped_ids=skipped)


def request_keys(request):
    """Exact singleton wire plus validation/context material; no answer reads.

    C0/A aliases are required to be the frozen canonical singleton aliases.
    We do not replace arbitrary strings, source identifiers, or provenance.
    Only the non-rendered local evidence candidate_id may differ.
    """
    payload = json.loads(request['prompt'])
    offered = request['offered']
    if list(offered) != ['C0'] or len(payload.get('candidates', [])) != 1:
        raise ValueError('requires canonical singleton request')
    if payload['candidates'][0].get('candidate') != 'C0':
        raise ValueError('noncanonical singleton alias')
    analysis = copy.deepcopy(request.get('analysis_evidence', {}))
    if 'C0' in analysis:
        analysis['C0'].pop('candidate_id', None)
    wire = {key:request.get(key) for key in ('system', 'prompt', 'thinking', 'evidence_mode')}
    return dict(wire_key=sha(wire), oracle_context_key=sha(dict(wire=wire,
        assertions=offered['C0'].get('assertions'), analysis_evidence=analysis)))
