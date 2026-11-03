"""Reuse replay's lexical shell discovery; never reinterpret a shell rc as PASS."""
from __future__ import annotations

import json
import posixpath
import re

from .shell import heredocs, segments, shell_words, resolve_path, source_writes, invocation_signal


SUFFIXES = ('.py', '.go', '.rs', '.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs', '.sh')
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def commands(actions, *, default_workdir='/app'):
    invocations, extra, issues, writes, mutations = [], set(), [], [], []
    for action in actions:
        command, cwd = action['command'], default_workdir
        docs = heredocs(command)
        for index, segment in enumerate(segments(command, docs)):
            try:
                words = shell_words(segment['text'])
                tokens = [word for word, _ in words]
            except ValueError as error:
                issues.append({'action_id': action['id'], 'reason': str(error), 'segment': segment['text']})
                continue
            doc = next((d for d in docs if segment['start'] <= d['header_end'] < segment['end']), None)
            if tokens[:1] == ['cd']:
                cwd = resolve_path(tokens[1], cwd) if len(tokens) == 2 and cwd else None
                continue
            if not cwd:
                issues.append({'action_id': action['id'], 'reason': 'working_directory_unresolved', 'segment': segment['text']})
                continue
            for path, content in source_writes(tokens, doc, cwd, words):
                extra.add(path)
                mutations.append({'action_id': action['id'], 'path': path})
                if content is not None:
                    writes.append({'action_id': action['id'], 'path': path, 'content': content})
            for token in tokens:
                if token.split('::')[0].endswith(SUFFIXES) and (path := resolve_path(token, cwd)):
                    extra.add(path)
            # A pipe's later commands are never included in the runner argv.
            argv = []
            for token in tokens:
                if token in {'|', '||', '&&', ';', '>', '>>', '<', '<<', '>&', '2>&1'}:
                    if token in {'>&', '>', '>>'} and argv and argv[-1] in {'1', '2'}:
                        argv.pop()
                    break
                argv.append(token)
            signal = invocation_signal(argv)
            common = {'id': action['id'] + ':' + str(index), 'action_id': action['id'],
                      'command_offsets': [segment['start'], segment['end']],
                      'shell_command': command, 'working_directory': cwd}
            if signal:
                runner = _framework(signal['lexical_tokens'])
                invocations.append({**common, 'signal': signal, 'framework': runner})
    return {'invocations': invocations, 'extra_paths': sorted(extra),
            'source_literals': writes, 'source_mutations': mutations, 'issues': issues}


def _framework(argv):
    if not argv:
        return 'unknown'
    name = posixpath.basename(argv[0])
    if name in {'pytest', 'py.test'} or argv[1:3] == ['-m', 'pytest']:
        return 'pytest'
    if argv[1:3] == ['-m', 'unittest']:
        return 'unittest'
    if name == 'go' and argv[1:2] == ['test']:
        return 'go'
    if name == 'cargo' and 'test' in argv[1:]:
        return 'rust'
    if name in {'jest', 'vitest', 'mocha', 'ava', 'tap', 'npm', 'pnpm', 'yarn', 'node', 'nodejs', 'bun', 'tsx', 'ts-node', 'deno'}:
        return 'javascript'
    return 'script'


def in_scope(unit, invocation):
    """A possible selection, not evidence that the runner collected the unit."""
    framework = invocation['framework']
    if unit['framework'] == 'pytest_or_unittest':
        if framework not in {'pytest', 'unittest', 'script'}:
            return False
    elif framework != unit['framework']:
        return False
    cwd = invocation['working_directory']
    argv = invocation['signal']['lexical_tokens']
    executable = posixpath.basename(argv[0])
    if executable in {'npm', 'pnpm', 'yarn'}:
        subcommand = next((index for index, token in enumerate(argv) if index and
                           re.fullmatch(r'(?:test|tests|spec)(?::[\w-]+)*', token)), None)
    else:
        subcommand = (next((index for index, token in enumerate(argv) if index and token == 'test'), None)
                      if executable in {'go', 'cargo', 'bun'} else None)
    # A package-manager filter can execute tests in a different package.
    # Its package root is not resolved here, so do not narrow the scope.
    signal = invocation['signal']
    wrapper = signal['wrapper_argv'] if 'invocation_wrapper' in signal else argv
    if posixpath.basename(wrapper[0]) == 'pnpm' and any(
            token in {'--filter', '-F'} or token.startswith('--filter=') for token in wrapper):
        return True
    paths = []
    # These values select names, configure the runner, or exclude files. They
    # are not positive file selectors (e.g. pytest --ignore tests/slow.py).
    value_options = {'-k', '-m', '-c', '-o', '--override-ini', '--rootdir', '--confcutdir',
                     '--ignore', '--ignore-glob', '--deselect', '--basetemp', '--junitxml',
                     '--junit-xml', '--log-file', '--cov', '--cov-report', '--tb',
                     '--maxfail', '-p', '--import-mode', '--color', '--capture',
                     '-run', '-bench', '-count', '-timeout', '-coverprofile', '-coverpkg',
                     '-tags', '-parallel', '-cpu', '-shuffle', '--manifest-path',
                     '--package', '--target', '--features', '--testNamePattern'}
    if executable == 'cargo':
        value_options.update({'--test', '--bin', '--example', '--bench'})
    skip_value = False
    for index, token in enumerate(argv[1:], 1):
        if index == subcommand:
            continue
        if skip_value:
            skip_value = False
            continue
        if token in value_options:
            skip_value = True
            continue
        if token.startswith('-'):
            continue
        stripped = token.split('::')[0]
        if stripped.endswith(SUFFIXES) or '/' in stripped or stripped in {'.', 'tests', 'test', 'spec'}:
            path = resolve_path(stripped.removesuffix('/...'), cwd)
            if path:
                paths.append((path, token.split('::')[1:]))
    if not paths:
        if invocation['signal']['kind'] in {'inline_executable_script', 'script_invocation', 'executable_file_candidate'}:
            return False
        return unit['path'].startswith(cwd.rstrip('/') + '/')
    for path, selectors in paths:
        if unit['path'] == path:
            return not selectors or unit['name'] == '::'.join(selectors).split('[', 1)[0] or unit['name'].startswith('::'.join(selectors) + '::')
        if unit['path'].startswith(path.rstrip('/') + '/'):
            return True
    return False


def source_may_change_during_action(invocation, unit, discovery):
    """Known compound-command writes make identical endpoints insufficient."""
    if any(r['action_id'] == invocation['action_id'] and r['path'] == unit['path']
           for r in discovery['source_mutations']):
        return True
    command = invocation['shell_command']
    return bool(re.search(r'\b(?:sed\s+-\S*i|perl\s+-\S*i|(?:cp|mv|rm)\s|git\s+(?:apply|checkout|restore|reset)\b)', command))


def result_notices(output, framework):
    if framework == 'go' and re.search(r'(?m)^ok\s+.*\(cached\)', ANSI.sub('', output)):
        return ['go_cached_results; named reports do not establish a fresh execution']
    return []


def named_results(output, framework):
    """Return only explicit named reports. A suite summary does not name tests."""
    text = ANSI.sub('', output or '')
    rows = []
    if framework in {'pytest', 'unittest'}:
        for m in re.finditer(r'(?m)^\s*(\S+\.py::[^\n]+?)\s+(PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)(?:\s|$)', text):
            rows.append({'name': m[1], 'status': m[2].lower(), 'evidence': m[0].strip()})
        for m in re.finditer(r'(?m)^\s*(test\S*) \(([^)]+)\) \.\.\. (ok|FAIL|ERROR|skipped[^\n]*)', text):
            rows.append({'name': m[2], 'status': 'passed' if m[3] == 'ok' else 'skipped' if m[3].startswith('skipped') else m[3].lower(), 'evidence': m[0].strip()})
    if framework == 'go':
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('Test') and row.get('Action') in {'pass', 'fail', 'skip'}:
                rows.append({'name': row['Test'], 'package': row.get('Package'), 'status': {'pass': 'passed', 'fail': 'failed', 'skip': 'skipped'}[row['Action']], 'evidence': line})
        for m in re.finditer(r'(?m)^\s*--- (PASS|FAIL|SKIP):\s+(\S+)\s', text):
            rows.append({'name': m[2], 'status': {'PASS': 'passed', 'FAIL': 'failed', 'SKIP': 'skipped'}[m[1]], 'evidence': m[0].strip()})
    if framework == 'rust':
        for m in re.finditer(r'(?m)^test (\S+) \.\.\. (ok|FAILED|ignored)(?:\s|$)', text):
            rows.append({'name': m[1], 'status': {'ok': 'passed', 'FAILED': 'failed', 'ignored': 'skipped'}[m[2]], 'evidence': m[0].strip()})
    if framework == 'javascript':
        # Jest's machine report supplies both a file and the complete suite name.
        try:
            report = json.loads(text)
        except ValueError:
            report = {}
        if isinstance(report, dict):
            for file in report.get('testResults', []):
                for result in file.get('assertionResults', []):
                    rows.append({'name': ' > '.join([*result.get('ancestorTitles', []), result.get('title', '')]),
                                 'path': file.get('name'), 'status': result.get('status', 'unknown'), 'evidence': result})
    return rows


def result_matches(unit, row, cwd):
    name = row['name']
    if unit['framework'] == 'pytest_or_unittest':
        if '::' in name and '.py::' in name:
            path, name = name.split('::', 1)
            return resolve_path(path, cwd) == unit['path'] and name.split('[', 1)[0] == unit['name']
        return name.endswith('.' + unit['name'].replace('::', '.'))
    if unit['framework'] == 'go':
        return name.split('/')[0] == unit['name']
    if unit['framework'] == 'rust':
        return name == unit['name']
    return name == unit['name'] and (not row.get('path') or resolve_path(row['path'], cwd) == unit['path'])
