"""Display original trajectory steps for manual inspection, never execute them."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def display_text(value):
    """Hide URL credentials in display only. Preserve the original evidence file."""
    return re.sub(r'(https?://)[^\s/\"\']+:[^\s/\"\']+@', r'\1[URL credentials hidden]@', str(value))


def observations(step):
    result = []
    for item in (step.get('observation') or {}).get('results', []):
        value = item.get('content', '')
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except ValueError:
                decoded = value
        else:
            decoded = value
        if isinstance(decoded, dict) and 'output' in decoded:
            result.append((decoded.get('returncode'), decoded['output']))
        else:
            result.append((None, decoded if isinstance(decoded, str) else json.dumps(decoded, ensure_ascii=False)))
    return result


def show(path, *, ids=None, index=False, reasoning=False, compact=False, brief=False):
    document = json.loads(path.read_text())
    print(json.dumps(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          total_steps=len(document['steps']),
                          display_note='URL credentials are hidden in display; raw evidence is unchanged.'), ensure_ascii=False))
    for step in document['steps']:
        sid = step['step_id']
        if ids is not None and sid not in ids:
            continue
        if brief:
            message = display_text(step.get('message') or '').replace('\n',' ')[:110]
            commands=[]
            for call in step.get('tool_calls') or []:
                args=call.get('arguments',{})
                if isinstance(args,str):
                    try:args=json.loads(args)
                    except ValueError:pass
                command=display_text(args.get('command','') if isinstance(args,dict) else args)
                commands.append(command.split('\n')[0][:150])
            outputs=[dict(rc=rc,chars=len(text),tail=display_text(text)[-90:].replace('\n',' ')) for rc,text in observations(step)]
            print(json.dumps(dict(step=sid,message=message,commands=commands,outputs=outputs),ensure_ascii=False))
            continue
        print(f"\nSTEP {sid} {step.get('source')} {step.get('timestamp')}")
        message = step.get('message') or ''
        if not isinstance(message, str):
            message = json.dumps(message, ensure_ascii=False)
        message = display_text(message)
        print('MESSAGE:', message[:140].replace('\n', ' ') if compact else message[:500] if index else message)
        for n, call in enumerate(step.get('tool_calls') or []):
            args = call.get('arguments', {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except ValueError: pass
            command = args.get('command', '') if isinstance(args, dict) else args
            command = display_text(command)
            print(f'COMMAND {n}:', command.split('\n')[0][:220] if compact else command[:700] if index else command)
            if index and len(command) > 700:
                print(f'COMMAND CHARACTERS: {len(command)}; expand this step to read the full command.')
        for n, (rc, output) in enumerate(observations(step)):
            print(f'OUTPUT {n}: returncode={rc}, characters={len(output)}')
            output = display_text(output)
            if compact:
                print('SUMMARY ONLY:', output[:110].replace('\n',' '), '...', output[-110:].replace('\n',' '))
            else:
                print(output[:250] + ('\n[INDEX SUMMARY ONLY]\n' + output[-250:] if len(output) > 500 else output[250:]) if index else output)
        if reasoning and step.get('reasoning_content'):
            print('PRIVATE REASONING (not a public program-analysis feature):', display_text(step['reasoning_content']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('trajectory', type=Path)
    parser.add_argument('--index', action='store_true')
    parser.add_argument('--compact', action='store_true')
    parser.add_argument('--brief', action='store_true')
    parser.add_argument('--steps', type=str)
    parser.add_argument('--reasoning', action='store_true')
    args = parser.parse_args()
    ids = None
    if args.steps:
        ids = set()
        for entry in args.steps.split(','):
            bounds = entry.split('-')
            ids.update(range(int(bounds[0]), int(bounds[-1]) + 1))
    show(args.trajectory, ids=ids, index=args.index or args.compact, reasoning=args.reasoning, compact=args.compact,brief=args.brief)
