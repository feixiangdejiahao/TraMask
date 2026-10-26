"""The same bounded helper-instance search with an open-term environment.

Requires only the default-preserving driver callback patch supplied separately;
the frozen literal-only extraction, composition and default search stay intact.
"""
from anchor_retrieval.syntax import Source, walk
from experimental.assertion_instances import generate as _driver
from experimental.assertion_instances.core import _one_statement_tree, _id
from experimental.generic_v2.generate import Budget, _canonical, _refine
from generic_composition.terms import Term
from .core import extract, compose


def novelty(record, text=None, *, references=None, max_nodes=1500):
    """Syntactic novelty includes actual binding IDs, not just name spelling."""
    if text is None:
        tree, start = record['tree'], record['span']['start_byte']
        refs = {(r['span']['start_byte'] - start, r['span']['end_byte'] - start): r['binding']
                for r in record['environment']['references']}
    else:
        code = 'package p\nfunc generated() {\n' + text + '\n}\n' if record['language'] == 'go' else text
        source = Source('novelty', code, record['language'])
        statement = next(n for n in walk(source.root) if n.type == 'expression_statement')
        tree, _ = _one_statement_tree(source, statement, max_nodes)
        start = statement.start_byte
        refs = {tuple(r['relative_span']): r['binding'] for r in references}

    def bound(node, path=()):
        span = tree.spans[path]
        identity = refs.get((span.start_byte - start, span.end_byte - start))
        atom = (node.atom, identity) if identity and not node.children else node.atom
        return Term(node.kind, atom, tuple(bound(c, path + (i,)) for i, c in enumerate(node.children)))

    # Inline binders are outside this adapter; there are no new locals to alpha
    # rename here. Distinct outer bindings intentionally keep distinct keys.
    return _canonical(bound(tree.term), {})


def generate(corpus, budget=Budget(), *, refine=_refine):
    output_environments = {}

    def checked(*args, **kwargs):
        result = compose(*args, **kwargs)
        if result['status'] == 'hypothesis':
            candidate = result['candidate']
            output_environments[(args[3]['instance_id'], candidate['edits'][0]['after'])] = \
                candidate['provenance']['lexical_check']['references']
        return result

    def key(record, text, max_nodes):
        return novelty(record, text, max_nodes=max_nodes,
                       references=None if text is None else output_environments[(record['instance_id'], text)])

    result = _driver.generate(corpus, budget, refine=refine, extract_instances=extract,
                              compose_instances=checked, novelty=key)
    result.update(algorithm='test_edit_analogy_open_assertion_instances',
                  novelty_precision='host_ast_trivia_ignored_with_actual_lexical_binding_identity')
    return result


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _driver.gate_evidence(corpus, generated, issue)
    environments, declarations, checks = {}, {}, {}
    for candidate in candidates:
        provenance = candidate['provenance']
        checks[candidate['rule_id']] = {'binding_correspondences': provenance['binding_correspondences'],
                                        'output_check': provenance['lexical_check']}
        for role, environment in provenance['source_environments'].items():
            uid = provenance['sources'][role]['instance_id']
            rows = []
            for reference in environment['references']:
                row = {k: reference[k] for k in ('name', 'span', 'binding', 'port', 'status', 'reason')}
                declaration = reference['declaration']
                if declaration:
                    did = _id('lexical_declaration', declaration['span'])
                    declarations[did] = declaration
                    row['declaration_id'] = did
                rows.append(row)
            environments[uid] = dict(environment, references=rows)
    evidence.update(lexical_environments=environments, lexical_declarations=declarations, binding_checks=checks,
                    environment_policy='References are open terms in the preserved C parent. A-to-C binding correspondences '
                    'are explicit substitutions, never value-equivalence claims. Same spelling alone proves nothing. '
                    'Unknown resolution, effects, aliasing, global state and builder behavior remain unproved. '
                    'Expected builder expressions are source syntax, never executed to manufacture an oracle.')
    return evidence, candidates
