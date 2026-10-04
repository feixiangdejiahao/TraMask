"""Freeze an ordered set of relation components and an exact semantic fallback.

All trials use the same component precedence. Preparation reads protocols only;
execution runs relation branches afresh and never replaces an audited alert.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import read
from scripts import run_documented_default_search as documentation
from scripts import run_byte_stream_search as stream
from scripts import run_checked_carrier_search as carrier
from scripts import run_error_finalization_search as finalization
from scripts import replay_uniform_second_gate as semantic
from scripts import replay_codec_guarded_semantics as codec
from scripts.run_contract_repair_search import frozen, verify, write

VERSION = 'ordered-source-relation-exact-semantic-chain.v4'
REGISTRY = dict(documentation=documentation, stream=stream, carrier=carrier,
                finalization=finalization, semantic=semantic)
SEMANTIC_RUNNERS = {semantic.VERSION: semantic, codec.VERSION: codec}


def _runner(name, version):
    runner = SEMANTIC_RUNNERS.get(version) if name == 'semantic' else REGISTRY.get(name)
    if runner is None or runner.VERSION != version:
        raise ValueError('Unexpected component protocol: ' + name)
    return runner


def _verify_receipts(value):
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            verify(value)
        for item in value.values():
            _verify_receipts(item)
    elif isinstance(value, list):
        for item in value:
            _verify_receipts(item)


def _replay_summary(source, prepared):
    verify(read(source/'seal.json'))
    old = read(source/'prepared.json')
    if old != prepared:
        raise ValueError('Native replay requires an identical complete component protocol')
    summary = read(source/'summary.json')
    if (summary['version'] != prepared['version']
            or sorted(row['case'] for row in summary['results']) != sorted(row['case'] for row in prepared['cases'])):
        raise ValueError('Native replay summary does not cover the complete frozen cohort')
    return frozen(source/'summary.json')


def prepare(args):
    sources = {}
    for entry in args.component:
        name, separator, path = entry.partition('=')
        if not separator or name not in REGISTRY or name in sources:
            raise ValueError('Each component must have one registered name and one path')
        sources[name] = Path(path)
    if list(sources)[-1:] != ['semantic'] or len(sources) < 2:
        raise ValueError('Require relation components followed by one semantic fallback')
    protocols, runners = {}, {}
    for name, source in sources.items():
        verify(read(source/'seal.json'))
        protocols[name] = read(source/'prepared.json')
        runners[name] = _runner(name, protocols[name]['version'])
    cases = sorted(protocols['semantic']['cases'])
    if any(sorted(row['case'] for row in protocols[name]['cases']) != cases
           for name in sources if name != 'semantic'):
        raise ValueError('All components must keep the same denominator')
    args.output.mkdir(parents=True, exist_ok=False)
    components = []
    for name in sources:
        destination = args.output/name/'prepared.json'
        write(destination, protocols[name])
        write(destination.parent/'seal.json', frozen(destination))
        component = dict(name=name, source=frozen(sources[name]/'prepared.json'), prepared=frozen(destination))
        replay_root = getattr(args, 'reuse_relations', None)
        if replay_root is not None and name != 'semantic':
            component['replay_summary'] = _replay_summary(replay_root/name, protocols[name])
        components.append(component)
    protocol = dict(version=VERSION, cases=cases, components=components,
        algorithm=[frozen(Path(__file__)), *[frozen(Path(runners[name].__file__)) for name in sources]],
        precedence=list(sources),
        policy='For each trial, emit the first available component alert in this fixed order. Do not replace after an audit rejects it.',
        preparation_reads='Sealed component protocols only; no output summary, known witness list, audit label or reference.',
        native_execution='Execute fresh unless an exact complete component protocol and immutable native summary are explicitly sealed for replay; no per-case native-cache selection.',
        semantic_execution='Exact-payload replay of the fixed first-stage alerts and historical high-reasoning gate.',
        external_model_calls=0, labels_used=False, retrospective=True,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output/'prepared.json', protocol)
    write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), prepared=frozen(args.output/'prepared.json'))


def run(args):
    root = args.input
    verify(read(root/'seal.json'))
    protocol = read(root/'prepared.json')
    for receipt in protocol['algorithm']:
        verify(receipt)
    for component in protocol['components']:
        verify(component['source'])
        verify(component['prepared'])
    if (root/'summary.json').exists():
        return read(root/'summary.json')
    runners = [(name, _runner(name, read(root/name/'prepared.json')['version']))
               for name in protocol['precedence']]
    replayed = set()
    for component in protocol['components']:
        if 'replay_summary' not in component:
            continue
        verify(component['replay_summary'])
        prepared = read(component['prepared']['path'])
        summary = read(component['replay_summary']['path'])
        if isinstance(prepared.get('algorithm'), dict):
            documentation.admission.verify_seal(prepared['algorithm'])
        _verify_receipts(prepared)
        _verify_receipts(summary)
        write(root/component['name']/'summary.json', summary)
        replayed.add(component['name'])
    for name, runner in runners:
        if not (root/name/'summary.json').exists():
            runner.run(SimpleNamespace(input=root/name))
    summaries = {name: read(root/name/'summary.json') for name, _ in runners}
    indices = {name: {row['case']: row for row in summaries[name]['results']}
               for name, _ in runners if name != 'semantic'}
    indices['semantic'] = {row['case']: row for row in summaries['semantic']['decisions']}
    decisions = []
    for case in protocol['cases']:
        row = dict(case=case, branch='abstain', alert=None)
        for name in protocol['precedence']:
            entry = indices[name].get(case, {})
            alert = (entry if entry.get('decision', {}).get('alarm_eligible') else None) if name == 'semantic' else entry.get('alert')
            if alert:
                row = dict(case=case, branch=name, alert=alert)
                break
        decisions.append(row)
    summary = dict(version=VERSION, denominator=len(protocol['cases']), decisions=decisions,
        alerts=[row for row in decisions if row['alert']],
        component_summaries={name: frozen(root/name/'summary.json') for name, _ in runners},
        fresh_native_executions=sum(summaries[name]['native_executions'] for name, _ in runners
                                    if name != 'semantic' and name not in replayed),
        replayed_native_executions=sum(summaries[name]['native_executions'] for name in replayed),
        semantic_historical_cost={key: summaries['semantic'][key] for key in
            ['first_stage_calls', 'first_stage_tokens', 'entire_second_gate_experiment_cost',
             'compatible_cached_reviews', 'compatible_cached_review_tokens']},
        fresh_provider_calls=0, retrospective=True, independent_audit_complete=False,
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json', summary)
    return dict(alerts=len(summary['alerts']), denominator=summary['denominator'],
                fresh_native_executions=summary['fresh_native_executions'],
                replayed_native_executions=summary['replayed_native_executions'], fresh_provider_calls=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--component', action='append', help='Ordered NAME=PATH; semantic must come last')
    parser.add_argument('--reuse-relations', type=Path, help='Replay every identical frozen native relation component from this prior chain')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
