"""P7 source-context completion control, separate from automatic main scores.

Only the previously reviewed missing original API source spans are added.
Human goals, labels, test code, and any later execution output are excluded.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_automatic_augmentation_io_repair as main
from scripts import run_automatic_augmentation_pilot as base

SOURCE_RECORD = ROOT / 'research/automatic_augmentation_diagnostic_goals_p_20261005.json'


def complete_context(payload, spans):
    import copy
    result = copy.deepcopy(payload)
    additions = []
    for index, span in enumerate(spans, 1):
        base.verify(span['source_file'])
        text = ''.join(Path(span['source_file']['path']).read_text().splitlines(keepends=True)
                       [span['start_line'] - 1:span['end_line']])
        if text != span['text']:
            raise ValueError('manual_original_source_span_mismatch')
        # Copy only raw original-source data. Discard all surrounding labels.
        additions.append(dict(evidence_id=f'D{index:04d}', kind='original_repository_source',
                              path=span['path'], start_line=span['start_line'],
                              end_line=span['end_line'], text=text))
    result['supplemental_original_source'] = additions
    return result


def request(system, payload, stage):
    req = main.request(system, payload, stage)
    req.update(manual_context_selection=True, diagnostic_only=True,
               manual_labels_included=False, supplied_human_goal=False)
    req['id'] = req['query_sha256'] = base.digest({k: v for k, v in req.items() if k not in {'id', 'query_sha256'}})
    return req


def run(root=main.DEFAULT_OUTPUT):
    protocol = main.load_protocol(root)
    case = next(c for c in protocol['cases'] if c['case'] == 'P7')
    batch = case['batches'][0]
    directory = root / 'context_diagnostic'
    prepared = directory / 'prepared.json'
    if prepared.exists():
        base.verify(base.read(directory / 'seal.json'))
        record = base.read(prepared)
        for key in ['algorithm', 'source_record', 'main_protocol', 'augmented_payload']:
            base.verify(record[key])
    else:
        source = next(c for c in base.read(SOURCE_RECORD)['cases'] if c['case'] == 'P7')
        payload = complete_context(base.read(batch['history_payload']['path']), source['additional_original_source'])
        base.write(directory / 'history_payload.json', payload)
        record = dict(main_method=False, diagnostic_only=True, case='P7', repeats=1,
                      algorithm=base.receipt(__file__), source_record=base.receipt(SOURCE_RECORD),
                      main_protocol=base.receipt(root / 'prepared.json'),
                      original_payload=batch['history_payload'],
                      augmented_payload=base.receipt(directory / 'history_payload.json'),
                      intervention='Only manually selected raw missing readonly/transform API source spans.',
                      human_goal_supplied=False, previous_output_supplied=False,
                      limitation='One context-completion draw cannot establish a causal average improvement.')
        base.write(prepared, record)
        base.write(directory / 'seal.json', base.receipt(prepared))
    diagnostic_batch = {**batch, 'history_payload': record['augmented_payload']}
    work = main._private(base.work_item, dict(request=request, dispatch_once=main.dispatch_once,
                                            parse_judgment=main.parse_judgment))
    return work(directory, case, diagnostic_batch, 'source_and_trajectory', 1)


if __name__ == '__main__':
    print(base.canonical(run()))
