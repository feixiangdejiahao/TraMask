"""Create readable local indexes from the preserved ATIF-v1.7 evidence."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent
selection = json.loads((ROOT / 'selection.json').read_text())
for row in selection['selected']:
    directory = ROOT / 'trials' / row['trial_name']
    trajectory = json.loads((directory / 'trajectory.json').read_text())
    lines = []
    commands = []
    for step_index, step in enumerate(trajectory['steps']):
        step_id = step['step_id']
        lines.append(f"\n===== STEP {step_id}: {step['source']} =====\n")
        lines.append(step['message'])
        if 'tool_calls' in step:
            observations = step['observation']['results']
            for index, call in enumerate(step['tool_calls']):
                command = call['arguments']['command']
                observation = json.loads(observations[index]['content'])
                output = (observation['output'] if 'output' in observation else
                          observation['output_head'] + f"\n[ORIGINAL OBSERVATION ELIDED {observation['elided_chars']} CHARS]\n" + observation['output_tail'])
                entry = {'step_id':step_id, 'trajectory_step_index':step_index,
                         'tool_call_id':call['tool_call_id'], 'call_index':index, 'command':command,
                         'returncode':observation['returncode'], 'output':output}
                commands.append(entry)
                lines.append(f"\nCOMMAND {index} (returncode={entry['returncode']})\n{command}\nOUTPUT\n{output}\n")
    (directory / 'trajectory.txt').write_text('\n'.join(lines))
    (directory / 'commands.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in commands))
    (directory / 'command_index.txt').write_text('\n'.join(f"{c['step_id']:03d}.{c['call_index']} rc={c['returncode']} {c['command'].splitlines()[0][:240]}" for c in commands)+'\n')
print('Indexed',len(selection['selected']),'trajectories')
