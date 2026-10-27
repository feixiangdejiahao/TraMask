from pathlib import Path
import ast
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone

ROOT = Path('/home/jhx/combination_coverage')
OLD = ROOT / 'results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01'
RUN = ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
OUT = RUN / 'observation/reviewer_A'
sys.path.insert(0, str(ROOT/'src'))
from tramask_rerun.replay_boundaries import resolve_submission_actions


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def receipt(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def load(sid):
    case = next(c for c in json.loads((OLD/'cases.json').read_text())['cases'] if c['screen_id'] == sid)
    directory = Path(case['input_directory'])
    doc = json.loads((directory/'trajectory.json').read_text())
    actions, boundary = resolve_submission_actions(doc)
    return case, actions, boundary


def action(sid, aid):
    return next(a for a in load(sid)[1] if a['id'] == aid)


def output(a):
    e = a['expected']
    return e.get('output') if isinstance(e.get('output'), str) else e.get('output_head', '') + '\n[ARCHIVED OUTPUT ELISION]\n' + e.get('output_tail', '')


def fragment(sid, aid, code, observed, meaning, fid, *, source_unit=None, source_aid=None, source_code=None, observation_aid=None):
    a = action(sid, aid)
    observation = action(sid, observation_aid) if observation_aid else a
    assert observed in output(observation), (sid, aid, 'observation excerpt missing')
    src = action(sid, source_aid) if source_aid else a
    if source_code is None:
        assert code in src['command'], (sid, aid, 'code excerpt missing')
        source = {'kind': 'exact_command_span', 'command_action': src['id'], 'start_char': src['command'].index(code), 'end_char': src['command'].index(code)+len(code)}
    else:
        assert code in source_code
        source = {'kind': 'decoded_historical_source_span', 'creation_action': src['id'], 'source_sha256': sha(source_code), 'start_char': source_code.index(code), 'end_char': source_code.index(code)+len(code)}
    return {'fragment_id': fid, 'source_unit_id': source_unit or aid, 'statement_or_condition': meaning,
            'code_span': source, 'code': code, 'code_sha256': sha(code),
            'step_id': a['step_id'], 'call_index': a['call_index'], 'tool_call_id': a['observation_mapping'].get('tool_call_id'),
            'command_sha256': a['command_sha256'], 'observation_sha256': a['observation_sha256'],
            'completion_observation_action': observation['id'],
            'execution_completion_receipt': {'action_id': observation['id'], 'step_id': observation['step_id'], 'call_index': observation['call_index'], 'command_sha256': observation['command_sha256'], 'observation_sha256': observation['observation_sha256']},
            'execution_reachability': observed, 'output_span': observed, 'recorded_returncode': a['expected']['returncode']}


def unit(sid, aid, name, code=None, *, result='pass', reached=None, check='assertion', uid=None, observation_aid=None):
    a = action(sid, aid)
    observation = action(sid, observation_aid) if observation_aid else a
    if reached: assert reached in output(observation)
    return {'unit_id': uid or aid, 'file_and_test_name': name, 'code_sha256': sha(code) if code is not None else None,
            'historical_call': {'step_id': a['step_id'], 'call_index': a['call_index'], 'tool_call_id': a['observation_mapping'].get('tool_call_id')},
            'command_sha256': a['command_sha256'], 'observation_sha256': a['observation_sha256'],
            'completion_observation_action': observation['id'],
            'execution_completion_receipt': {'action_id': observation['id'], 'step_id': observation['step_id'], 'call_index': observation['call_index'], 'command_sha256': observation['command_sha256'], 'observation_sha256': observation['observation_sha256']},
            'execution_status': 'factor_reached' if reached else 'unit_invoked_only', 'unit_result': result,
            'reached_evidence': reached, 'check_kind': check}


def literal(sid, aid, variable):
    command = action(sid, aid)['command']
    match = re.search(r"python3?\s+(?:-\s+)?<<\s*['\"]?(\w+)['\"]?\n", command)
    assert match
    source = command[match.end():].split('\n'+match[1], 1)[0]
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == variable for x in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(variable)


def added_file(sid, path):
    case = load(sid)[0]
    text = (Path(case['input_directory'])/'model.patch').read_text()
    sections = text.split('diff --git ')
    section = next(s for s in sections if s.startswith('a/'+path+' b/'+path+'\n'))
    assert '\n--- /dev/null\n' in section
    lines = section.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith('@@'))
    return ''.join(line[1:] for line in lines[start+1:] if line.startswith('+'))


def heredoc(sid, aid):
    command = action(sid, aid)['command']
    match = re.search(r"<<['\"]?(\w+)['\"]?\n", command)
    assert match
    return command[match.end():].split('\n'+match[1], 1)[0]+'\n'


def base(sid, terms):
    c, actions, boundary = load(sid)
    p = copy.deepcopy(json.loads((RUN/'review_template.json').read_text()))
    p.update(case_id=sid, trial=c['trial'], task=c['task'], known_case=c.get('known_case'),
             reviewer={'identity':'/root/fragment_runtime_inventory', 'assignment':'independent reviewer A', 'current_reviewer_B_accessed':False, 'current_root_conclusions_accessed':False},
             review_status='reviewed', observed_at=datetime.now(timezone.utc).isoformat())
    p['source_receipts'] = [receipt(Path(c['input_directory'])/n) for n in ['instruction.md','model.patch','trajectory.json']]
    p['source_receipts'] += [receipt(Path(c['task_directory'])/'tests/test.patch'), receipt(Path(c['task_directory'])/'tests/config.json'), receipt(Path(c['archived_verifier_directory'])/'test-stdout.txt')]
    p['search_coverage'].update(total_executed_calls=len(actions), actions_inspected=[a['id'] for a in actions], aliases_and_terms=terms,
        unavailable_evidence=[{'action_id':a['id'],'output_form':a['output_form'],'elided_chars':a['expected'].get('elided_chars')} for a in actions if 'elided' in a['output_form']],
        notes='All observed call commands/results indexed and semantic aliases searched; relevant test definitions, revisions, invocations and outputs manually inspected. Explicit unexecuted submission calls excluded; output elisions are not reconstructed.')
    p['history_boundary'] = {k:boundary[k] for k in ['raw_tool_call_count','executed_action_count','explicitly_unexecuted_calls','output_elision_action_ids']}
    return p


def save(sid, value):
    p = OUT/(sid+'.json')
    if p.exists(): raise FileExistsError(p)
    assert value['case_id'] == sid
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print('SAVED',str(p))


def overview(sid):
    c, actions, boundary = load(sid)
    print('CASE',sid,c['task'],c['trial'])
    print('ISSUE\n'+(Path(c['input_directory'])/'instruction.md').read_text())
    patch=(Path(c['task_directory'])/'tests/test.patch').read_text()
    print('VERIFIER TEST DECLARATIONS')
    declarations = []
    for line in patch.splitlines():
        if re.search(r'^\+(?:def test|async def test|func Test|\s*(?:it|test|describe)\(|\s*#\[test\])',line): declarations.append(line)
    print('\n'.join(declarations[:24])); print('total declarations',len(declarations))
    out=(Path(c['archived_verifier_directory'])/'test-stdout.txt').read_text()
    marker=out.find('[verifier] ===== FAILURES')
    relevant = out[marker:] if marker>=0 else out[-6000:]
    print('VERIFIER FAILURES\n'+relevant[-6500:])
    print('ALL ACTIONS',len(actions),'ELISIONS',boundary['output_elision_action_ids'])
    for a in actions: print(a['id'],a['expected']['returncode'],a['command'].replace('\n',' ')[:105])


if __name__=='__main__':
    mode, sid = sys.argv[1:3]
    if mode=='overview': overview(sid)
    elif mode=='show':
        for aid in sys.argv[3:]:
            a=action(sid,aid);print('\nACTION',aid,'\nCOMMAND\n'+a['command']+'\nOUTPUT\n'+output(a))
    elif mode=='search':
        pattern=re.compile(sys.argv[3],re.I)
        for a in load(sid)[1]:
            for kind,text in [('command',a['command']),('output',output(a))]:
                hits=[line for line in text.splitlines() if pattern.search(line)]
                if hits: print(a['id'],kind,'\n'+'\n'.join(hits[:60]))
