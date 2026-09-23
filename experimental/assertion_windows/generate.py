"""Bounded window-granularity search, reusing the existing instance driver."""
import re
import textwrap

from anchor_retrieval.syntax import Source, walk
from experimental.assertion_instances import generate as _driver
from experimental.generic_v2.generate import Budget, _binding_labels, _canonical, _refine
from generic_composition.engine import gate_evidence as _source_evidence
from generic_composition.terms import from_source
from .compose import compose, prepare_environment
from .extract import extract as _extract


def _novelty(corpus, record, text, max_nodes):
    text = record['text'] if text is None else text
    language = corpus['language']
    if language == 'python':
        raw = corpus['sources'][record['span']['path']]['code'].encode()
        lo = record['span']['start_byte']
        prefix = raw[raw.rfind(b'\n', 0, lo) + 1:lo].decode()
        indentation = re.match(r'[ \t]*', prefix).group()
        source = Source('window.py', textwrap.dedent(indentation + text), language)
        node = source.root
    else:
        prefix = 'package p\nfunc generated() {\n' if language == 'go' else 'function generated() {\n'
        source = Source('window', prefix + text + '\n}', language)
        node = next(n for n in walk(source.root) if n.type in {'block', 'statement_block'})
    converted = from_source(source, node, max_nodes=max_nodes)
    return _canonical(converted.term, _binding_labels(source, node, converted, record['test']['parameters']))


def generate(corpus, budget=Budget(), *, refine=_refine):
    cache = {}

    def extract_instances(*args, **kwargs):
        result = _extract(*args, **kwargs)
        result['instances'] = [prepare_environment(corpus, record, cache) for record in result['instances']]
        return result

    result = _driver.generate(corpus, budget, refine=refine, extract_instances=extract_instances,
                              compose_instances=compose,
                              novelty=lambda record, text, max_nodes: _novelty(corpus, record, text, max_nodes))
    result.update(algorithm='test_edit_analogy_contiguous_assertion_windows',
                  unit='source_backed_contiguous_observation_window',
                  gap_order_policy='fixed_residual_first; alternative order is not searched',
                  novelty_precision='host_window_ast_trivia_ignored_restricted_unique_local_alpha')
    return result


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _source_evidence(corpus, generated, issue)
    windows, sources, environments, binding_checks = {}, {}, {}, {}
    for candidate in candidates:
        provenance = candidate['provenance']
        rid = candidate['rule_id']
        sources[rid] = {}
        binding_checks[rid] = provenance['lexical_check']
        for role, source in provenance['sources'].items():
            uid = source['instance_id']
            windows[uid] = source
            sources[rid][role] = uid
            environments[uid] = provenance['source_environments'][role]
    definitions = {}
    for tid in evidence['source_tests']:
        for helper in corpus['tests'][tid]['support']['helpers']:
            from generic_composition.corpus import source_text
            definitions[helper['id']] = {'span': helper['span'], 'code': source_text(corpus, helper['span'])}
    evidence.pop('test_helpers', None)
    evidence.update(assertion_windows=windows, analogy_sources=sources, external_environments=environments,
                    binding_checks=binding_checks, helper_definitions=definitions,
                    unit_policy='A/B/C are contiguous observation windows and may come from the same parent test. '
                    'C parent code before and after the selected window is preserved by the exact edit span.',
                    composition_policy='Required definitions and the observation are one unit; intervening C gap statements '
                    'must remain byte-identical in their original order, once each. B additions use residual-first order. '
                    'Definition/effect slicing is approximate and does not establish absence of alias or global effects.',
                    oracle_policy='Input, setup and oracle syntax are jointly transported from source. '
                    'Judge every assertion in the COMPLETE edited parent: changed live-out definitions or mutations '
                    'can invalidate later assertions even when the selected observation is valid. '
                    'Reconstruction and binding checks do not prove state equivalence or oracle correctness.')
    return evidence, candidates
