"""Keep the original complete-test decoder and attach exact source provenance."""
from relation_search import contract_gap_proposals as core
from relation_search import declaration_contract_planning as planning
from relation_search.direct_generation_provenance import attach

VERSION = core.VERSION
POLICY = dict(core.POLICY, context_planning=planning.POLICY,
              comparative_limit='Adds model retrieval planning and documentation representation changes; not a pure catalog-order ablation.')


def decide(corpus, frontend, prepared, response, *, finish_reason='stop'):
    result = core.decide(corpus, frontend, prepared, response, finish_reason=finish_reason)
    result['candidates'] = [attach(corpus, candidate) for candidate in result['candidates']]
    return result
