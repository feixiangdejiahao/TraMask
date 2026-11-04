"""Research CLI for replay, slicing, behavior comparison and test baselines."""
import argparse
import json
from pathlib import Path

from .baseline import run_selected_test
from .artifacts import relative_references
from .collection import collect_tests
from .history import history_records
from .replay import load_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    collect = commands.add_parser('collect', help='Replay and collect test versions and historical executions')
    collect.add_argument('--case-id', required=True)
    collect.add_argument('--input-directory', type=Path, required=True)
    collect.add_argument('--out', type=Path, required=True)
    collect.add_argument('--base-commit')
    collect.add_argument('--shared-chunks', type=Path, help='Share captured chunks with other collections')
    history = commands.add_parser('history', help='Export Step B id/text/source material from an A manifest')
    history.add_argument('--manifest', type=Path, required=True)
    history.add_argument('--out', type=Path, required=True, help='New output JSON file')
    targets = commands.add_parser('targets', help='Select Step D pre-slice entries and retain the complete B workset')
    targets.add_argument('--manifest', type=Path, required=True)
    targets.add_argument('--out', type=Path, required=True, help='New output JSON file')
    slicing=commands.add_parser('slice',help='Slice historical source versions and their observed IO contexts')
    slicing.add_argument('--manifest',type=Path,required=True)
    slicing.add_argument('--out',type=Path,required=True)
    slicing.add_argument('--source',help='A source reference returned by targets/history')
    slicing.add_argument('--source-base',type=Path,help='Directory containing an exported relative source reference')
    slicing.add_argument('--start',type=int)
    slicing.add_argument('--end',type=int)
    slicing.add_argument('--consumer',help='Restrict to one observed read/code-input event')
    evidence = commands.add_parser('slice-evidence', help='Read a shared slice with behavior and original-material references')
    evidence.add_argument('--directory', type=Path, required=True, help='Output directory of a batch slice run')
    evidence.add_argument('--view', required=True, help='View path relative to that directory, e.g. views/0.json')
    evidence.add_argument('--out', type=Path, required=True)
    comparison=commands.add_parser('compare',help='Align behavior roles and cluster queries from current slices')
    comparison.add_argument('--directory',type=Path,required=True,help='Output directory of a new batch slice run')
    comparison.add_argument('--out',type=Path,required=True)
    comparison.add_argument('--partitions',nargs='+',choices=['ports','relations','flow','boundary'],default=['ports'])
    alignment=commands.add_parser('align',help='Align two concrete members and extract their behavior differences')
    alignment.add_argument('--directory',type=Path,required=True,help='The batch slice directory used by compare')
    alignment.add_argument('--left',nargs=3,required=True,metavar=('VIEW','SOURCE','OPERATION'))
    alignment.add_argument('--right',nargs=3,required=True,metavar=('VIEW','SOURCE','OPERATION'))
    alignment.add_argument('--out',type=Path,required=True)
    candidate=commands.add_parser('candidate-materials',help='Read materials attached to a cluster candidate')
    candidate.add_argument('--directory',type=Path,required=True)
    candidate.add_argument('--classes',type=int,nargs=2,required=True)
    candidate.add_argument('--members',type=int,nargs=2)
    candidate.add_argument('--partition',choices=['ports','relations','flow','boundary'],default='ports')
    candidate.add_argument('--out',type=Path,required=True)
    baseline = commands.add_parser('baseline', help='Run a retained test on its submitted checkpoint')
    baseline.add_argument('--manifest', type=Path, required=True)
    baseline.add_argument('--test-id', required=True)
    baseline.add_argument('--command', required=True)
    baseline.add_argument('--out', type=Path, required=True)
    baseline.add_argument('--workdir', default='/app')
    baseline.add_argument('--timeout', type=int, default=120)
    baseline.add_argument('--build', action='append', default=[])
    baseline.add_argument('--env', action='append', default=[], metavar='NAME=VALUE')
    args = parser.parse_args()
    if args.action=='compare':
        from .comparison import compare_slices
        summary=compare_slices(args.directory,args.out,modes=args.partitions)
        print(json.dumps(summary,ensure_ascii=False))
        return 0
    if args.action=='align':
        from .comparison import load_slice_comparison
        from .artifacts import write_json
        comparison,_,_=load_slice_comparison(args.directory)
        left,right=[(int(row[0]),*row[1:]) for row in (args.left,args.right)]
        packet=comparison.align(left,right)
        write_json(args.out,packet)
        print(json.dumps({'output':str(args.out),'changed_relations':len(packet['difference']['addresses'])}))
        return 0
    if args.action=='candidate-materials':
        from .behavior_clusters import read_candidate_materials
        from .artifacts import write_json
        packet=read_candidate_materials(args.directory,args.classes,member_views=args.members,partition=args.partition)
        write_json(args.out,packet)
        print(json.dumps({'output':str(args.out),'materials':len(packet['candidate_materials'])}))
        return 0
    if args.action == 'slice-evidence':
        from .slicing import read_slice_evidence
        from .artifacts import write_json
        packet = read_slice_evidence(args.directory, args.view)
        write_json(args.out, packet)
        print(json.dumps({'output': str(args.out), 'sources': len(packet['behavior_sources'])}))
        return 0
    if args.action=='slice':
        from .slicing import slice_targets,slice_location
        if args.source is None:
            result=slice_targets(args.manifest,args.out)
        else:
            if args.start is None or args.end is None:parser.error('--source requires --start and --end')
            args.out.mkdir(parents=True)
            result=slice_location(args.manifest,args.source,args.start,args.end,consumer=args.consumer,base=args.source_base)
            from .artifacts import write_json
            write_json(args.out/'slice.json',relative_references(result,args.out))
        print(json.dumps({'output':str(args.out),'result':result if args.source is None else len(result)}))
        return 0
    if args.action == 'targets':
        from .targets import targets_from_manifest
        result = targets_from_manifest(args.manifest)
        with args.out.open('x', encoding='utf-8') as output:
            json.dump(relative_references(result,args.out.parent), output, ensure_ascii=False, indent=2)
            output.write('\n')
        print(json.dumps({'targets': len(result['targets']), 'records': len(result['records']),
                          **result['metrics'], 'parse_errors': len(result['parse_errors']),
                          'output': str(args.out)}))
        return 0
    if args.action == 'history':
        records = history_records(args.manifest)
        with args.out.open('x', encoding='utf-8') as output:
            json.dump(relative_references(records,args.out.parent), output, ensure_ascii=False, indent=2)
            output.write('\n')
        print(json.dumps({'records': len(records), 'output': str(args.out)}))
        return 0
    if args.action == 'collect':
        case = load_case(args.case_id, args.input_directory, args.base_commit)
        result = collect_tests(case, args.input_directory, args.out, shared_chunks=args.shared_chunks)
        print(json.dumps({k: result[k] for k in ('status', 'state_validation_passed', 'step_a')}, indent=2))
        return 0 if result['state_validation_passed'] else 2
    result = run_selected_test(args.manifest, args.test_id, args.command, args.out,
                               workdir=args.workdir, timeout=args.timeout, build_commands=args.build,
                               env=dict(value.split('=', 1) for value in args.env))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['runner_status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
