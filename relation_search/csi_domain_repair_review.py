"""Fresh complete-test review plus a separate, immutable input-domain gate."""
from __future__ import annotations

import copy
import json

from relation_search import compact_contract_guarded as whole_test
from relation_search import csi_input_domain_guard as domain
from relation_search.csi_domain_repair import canonical_sha, sha

VERSION = 'complete-test-and-csi-repair-domain.v1'


def prepare(corpus, frontend, candidate, issue, **kwargs):
    result = whole_test.prepare(corpus, frontend, candidate, issue, **kwargs)
    request = result.get('request')
    if request is None:
        return result
    payload = json.loads(request['prompt'])
    gate = domain.analyze(payload, analysis=result['analysis'], sources=corpus['sources'])
    metadata = dict(guard=gate, repaired_value=candidate['csi_repair']['value_after'])
    request['csi_repair_domain'] = metadata
    request['csi_repair_domain_sha256'] = canonical_sha(metadata)
    result['independent_source_domain'] = metadata
    return result


def domain_allowed(request):
    metadata = request['csi_repair_domain']
    if request['csi_repair_domain_sha256'] != canonical_sha(metadata):
        raise ValueError('Frozen repaired input-domain metadata differs')
    gate = metadata['guard']
    payload = json.loads(request['prompt'])
    if any(gate[key+'_sha256'] != sha(payload[key]) for key in ('original_test', 'modified_test')):
        raise ValueError('Input-domain gate refers to another complete test')
    # Outside scope cannot establish the protocol association needed for this
    # constructor, even though outside scope does not block generic CSI replay.
    return (gate['decision'] == 'allow' and gate['status'] == 'bounded_input_domain_checked'
            and gate['allow_prior_gate'] is True
            and any(check.get('value') == metadata['repaired_value']
                    and check.get('decision') == 'allow' and check.get('positive_key_result') is True
                    and check.get('domain_binding') for check in gate.get('checks', [])))


def decide(request, payload, *, finish_reason='stop'):
    full = whole_test.decide(request, payload, finish_reason=finish_reason)
    permitted = domain_allowed(request)
    result = copy.deepcopy(full)
    result.update(full_test_review=full, source_domain_allowed=permitted,
                  source_domain_receipt=request['csi_repair_domain_sha256'])
    if not permitted and full.get('status') == 'semantic_supported':
        result.update(status='unknown', alarm_eligible=False, semantic_validity='unconfirmed',
                      reason='full_test_review_cannot_discharge_unproved_source_protocol_binding')
    return result
