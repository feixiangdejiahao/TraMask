"""Check the portable report against current judgments and primary evidence.

The audit checks completeness, provenance, bilingual structure and offline packaging;
it does not independently re-label the scientific judgments or run repair trials.
"""
from collections import Counter
from datetime import datetime, timezone
import base64
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'research/deepswe_counterfactual_review_20261021'
CONTENT = ROOT / 'research/deepswe_report_presentation_20261022'
VISUALS = ROOT / 'research/deepswe_gap_visuals_20261022'
EVIDENCE = ROOT / 'results/failure_analysis/20261021_counterfactual_gap_n211_r01'
DEST = ROOT / 'docs/20261022_deepswe_failure_analysis_n211.html'
OUTPUT = ROOT / 'results/failure_analysis/20261022_standalone_report_n211_r01/audit.json'
FIELDS = {'evaluation', 'combination', 'validation', 'counterfactual'}
FORBIDDEN_KEYS = {'old_verdict', 'old_verdict_reason', 'old_gaps', 'source_windows'}
METRICS = ('f2p_passed', 'f2p_total', 'p2p_passed', 'p2p_total')


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.ids, self.cards, self.references = [], [], []
        self.scripts, self.styles, self.visible = [], [], []
        self.active_script = None
        self.in_style = False
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if 'trial' in attrs.get('class', '').split():
            self.cards.append(attrs)
        for attr in ('href', 'src', 'srcset', 'data', 'poster', 'action'):
            if attrs.get(attr):
                self.references.append({'tag': tag, 'attribute': attr, 'value': attrs[attr]})
        if tag == 'script':
            self.scripts.append({'attrs': attrs, 'text': ''})
            self.active_script = self.scripts[-1]
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active_script = None
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.active_script is not None:
            self.active_script['text'] += data
        elif self.in_style:
            self.styles.append(data)
        else:
            self.visible.append(data)


def check_keys(value, location='payload'):
    if isinstance(value, dict):
        require(not FORBIDDEN_KEYS.intersection(value), f'Historical review field at {location}')
        for key, child in value.items():
            check_keys(child, f'{location}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_keys(child, f'{location}[{index}]')


def unpack_payload(page):
    """Verify every embedded chunk before reconstructing the scientific payload.

    Browser startup reads only the small manifest; this audit deliberately opens
    all chunks to check that deferred content is as complete as the reader data.
    """
    data_scripts = [s for s in page.scripts if s['attrs'].get('id') == 'report-data']
    require(len(data_scripts) == 1 and data_scripts[0]['attrs'].get('type') == 'application/json', 'Missing portable JSON manifest')
    manifest = json.loads(data_scripts[0]['text'])
    require(manifest.get('schema_version') == 'deepswe-portable-chunks.v2', 'Unexpected portable data schema')
    require(manifest.get('encoding') == 'gzip-base64', 'Unexpected chunk encoding')
    check_keys(manifest)
    chunk_scripts = [s for s in page.scripts if s['attrs'].get('type') == 'application/octet-stream']
    chunks = {s['attrs'].get('id'): s for s in chunk_scripts}
    require(len(chunks) == len(chunk_scripts) and None not in chunks, 'Duplicate or unnamed embedded chunk')
    used, decoded = set(), {}

    def unpack(descriptor, where, as_json=False):
        cid = descriptor.get('chunk')
        require(cid in chunks, f'{where}: missing embedded chunk {cid}')
        used.add(cid)
        if cid not in decoded:
            script = chunks[cid]
            require(script['attrs'].get('data-encoding') == 'gzip-base64', f'{where}: incorrect chunk encoding')
            compressed = base64.b64decode(script['text'].strip(), validate=True)
            raw = gzip.decompress(compressed)
            decoded[cid] = (raw, len(compressed))
        raw, compressed_bytes = decoded[cid]
        require(hashlib.sha256(raw).hexdigest() == descriptor.get('sha256'), f'{where}: chunk hash differs')
        for field, size in (('bytes', len(raw)), ('compressed_bytes', compressed_bytes)):
            if field in descriptor:
                require(descriptor[field] == size, f'{where}: incorrect {field}')
        value = raw.decode('utf-8')
        return json.loads(value) if as_json else value

    assets = {aid: unpack(item, f'asset {aid}') for aid, item in manifest['assets'].items()}
    require(all(item.get('chunk') == aid for aid, item in manifest['assets'].items()), 'Asset IDs must identify their own chunks')
    cases, tasks, referenced_assets = {}, {}, set()
    for task, descriptor in manifest['tasks'].items():
        aid = descriptor.get('asset')
        require(aid in assets, f'{task}: missing evaluation test source asset')
        referenced_assets.add(aid)
        tasks[task] = {'test_patch': assets[aid]}
    for trial, descriptor in manifest['cases'].items():
        require('issue' not in descriptor and 'patch' not in descriptor and 'analysis' not in descriptor, f'{trial}: full source/analysis is not deferred')
        case = unpack(descriptor, f'trial {trial}', as_json=True)
        check_keys(case, f'case.{trial}')
        require('issue' not in case and 'patch' not in case, f'{trial}: full source duplicated in trial chunk')
        for field in ('n', 'trial', 'task', 'repository', 'language', 'decision', 'metric', 'metrics', 'assets'):
            require(case[field] == descriptor[field], f'{trial}: manifest {field} differs from trial chunk')
        require(set(case['assets']) == {'issue', 'patch', 'evaluation'}, f'{trial}: incomplete full-source references')
        for kind, aid in case['assets'].items():
            require(aid in assets, f'{trial}: missing {kind} source asset')
            referenced_assets.add(aid)
        require(case['assets']['evaluation'] == manifest['tasks'][case['task']]['asset'], f'{trial}: evaluation asset differs from task')
        case['issue'] = assets[case['assets']['issue']]
        case['patch'] = assets[case['assets']['patch']]
        story = unpack(descriptor['story'], f'{trial}: test-generation trajectory', as_json=True)
        check_keys(story, f'story.{trial}')
        require(case['test_story']['intro'] == story['intro'], f'{trial}: deferred story intro changed')
        require(case['test_story']['recorded_events'] == len(story['events']), f'{trial}: deferred story count changed')
        require(case['test_story']['events'] == [{k: e[k] for k in ('step', 'kind', 'title')} for e in story['events']], f'{trial}: story outline differs')
        require(all('quotes' not in e and 'actions' not in e for e in case['test_story']['events']), f'{trial}: story evidence not deferred')
        case['test_story'] = story
        cases[trial] = case
    require(referenced_assets == set(assets), 'Unused embedded full-source asset')
    search = unpack(manifest['search'], 'search index', as_json=True)
    require(set(search) == set(cases), 'Search index differs from embedded trial cohort')
    for trial, case in cases.items():
        label = manifest['labels'][case['decision']]
        values = [case['trial'], case['task'], case['repository'], case['language'], case['decision'],
                  *case['overview'].values(), *case['analysis']['zh'].values(), *case['analysis']['en'].values(),
                  label['zh'], label['en'], *[f['name'] for f in case['evaluation']['failure_index']]]
        values.extend(case['gap_table']['title'].values())
        values.extend(case['gap_table']['note'].values())
        for column in case['gap_table']['columns']:
            values.extend(column[k] for k in ('zh', 'en'))
        for scenario in case['gap_table']['rows']:
            for cell in scenario['cells']:
                values.extend(cell[k] for k in ('zh', 'en'))
        values.extend(case['test_story']['intro'].values())
        for event in case['test_story']['events']:
            values.extend(event['title'].values())
        require(search[trial] == ' '.join(values).lower(), f'{trial}: incomplete or changed search index')
    require(used == set(chunks), 'Orphan or unreferenced embedded chunk')
    counts = {'embedded_chunks_verified': len(chunks), 'full_source_assets_verified': len(assets),
              'search_index_trials_verified': len(search), 'deferred_trial_chunks_verified': len(cases),
              'deferred_story_chunks_verified': len(cases),
              'chunk_encoding': manifest['encoding'], 'initial_manifest_bytes': len(data_scripts[0]['text'].encode())}
    return {'cases': cases, 'tasks': tasks, 'labels': manifest['labels']}, counts


def check_visuals(case, authored, steps, trial, decision):
    require(case['gap_table'] == authored['gap_table'], f'{trial}: table differs from authored record')
    table, story = case['gap_table'], case['test_story']
    for value in [table['title'], table['note'], *table['columns']]:
        require(all(isinstance(value.get(lang), str) and value[lang].strip() for lang in ('zh','en')), f'{trial}: incomplete bilingual table')
    states = []
    for row in table['rows']:
        require(len(row['cells']) == len(table['columns']), f'{trial}: non-rectangular coverage table')
        require(all(sid in steps for sid in row['steps']), f'{trial}: table cites missing step')
        for cell in row['cells']:
            require(all(isinstance(cell.get(lang), str) and cell[lang].strip() for lang in ('zh','en')), f'{trial}: incomplete bilingual table cell')
            if 'state' in cell:
                require(cell['state'] in {'observed','gap','weak','exposed','unknown','not_applicable'}, f'{trial}: unknown table state')
                states.append(cell['state'])
    require(states, f'{trial}: table lacks observation states')
    if decision not in ('supported','plausible'):
        require('gap' not in states, f'{trial}: unconfirmed attribution shown as a definite gap')
    require(story['intro'] == authored['test_story']['intro'] and story['takeaway'] == authored['test_story']['takeaway'], f'{trial}: story context changed')
    require(story['total_steps'] == len(steps), f'{trial}: wrong trajectory length')
    require(len(story['events']) == len(authored['test_story']['events']), f'{trial}: incomplete authored story')
    event_ids = [event['step'] for event in story['events']]
    require(event_ids == sorted(set(event_ids)), f'{trial}: story not in trajectory order')
    for event, source in zip(story['events'], authored['test_story']['events']):
        for key in ('step','kind','title','summary','relation'):
            require(event[key] == source[key], f'{trial}: authored event {key} changed')
        require([{k:q[k] for k in ('field','text')} for q in event['quotes']] == source['quotes'], f'{trial}: authored quote changed')
    all_events = story['events'] + story['references']
    all_ids = [event['step'] for event in all_events]
    require(len(all_ids) == len(set(all_ids)), f'{trial}: duplicate narrative/evidence steps')
    require({sid for row in table['rows'] for sid in row['steps']} <= set(all_ids), f'{trial}: table evidence cannot be opened')
    quote_count = 0
    for event in all_events:
        sid = event['step']
        require(sid in steps, f'{trial}: invented trajectory event')
        original = steps[sid]
        require(event['timestamp'] == original.get('timestamp',''), f'{trial}: event timestamp changed')
        for quote in event['quotes']:
            text = original.get(quote['field'],'')
            require(quote['field'] in ('reasoning_content','message'), f'{trial}: unsupported original-text field')
            require(text[quote['char_start']:quote['char_end']] == quote['text'], f'{trial}: quote not found at original offsets')
            require(quote['text'].strip(), f'{trial}: empty source quote')
            quote_count += 1
        require(len(event['actions']) == len(original.get('tool_calls',[])), f'{trial}: missing recorded action')
        for action, call in zip(event['actions'],original.get('tool_calls',[])):
            args = call.get('arguments',{})
            if isinstance(args,str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {'command':args}
            command = str(args.get('command','')) if isinstance(args,dict) else ''
            require(action['tool'] == call.get('function_name','tool'), f'{trial}: tool name changed')
            check_clipped(action['command'],command,f'{trial}: narrative step {sid} action')
        check_clipped(event['output'],observation_text(original),f'{trial}: narrative step {sid} feedback')
    return {'events':len(story['events']),'quotes':quote_count,'columns':len(table['columns']),'layout':table['layout']}


def check_excerpt(excerpt, source, where):
    """Check every numbered displayed line against its primary-source position."""
    require(isinstance(excerpt, dict) and isinstance(excerpt.get('text'), str), f'{where}: no excerpt')
    lines = source.splitlines()
    require(excerpt.get('line_count') == len(lines), f'{where}: wrong source line count')
    seen = set()
    for line in excerpt['text'].splitlines():
        if line.strip() == '…':
            continue
        match = re.match(r'^\s*(\d+)  (.*)$', line)
        require(match is not None, f'{where}: unnumbered excerpt line')
        number, text = int(match[1]), match[2]
        require(0 < number <= len(lines) and number not in seen, f'{where}: invalid/duplicate line number {number}')
        require(lines[number - 1] == text, f'{where}: source differs at line {number}')
        seen.add(number)


def check_clipped(excerpt, source, where):
    require(isinstance(excerpt, dict) and isinstance(excerpt.get('text'), str), f'{where}: no text')
    text = excerpt['text']
    if not excerpt.get('truncated'):
        require(text == source, f'{where}: text differs')
    else:
        marker = '\n\n[…]\n\n'
        require(text.count(marker) == 1, f'{where}: missing omission marker')
        beginning, ending = text.split(marker)
        require(source.startswith(beginning) and source.endswith(ending), f'{where}: clipped text differs')


def observation_text(step):
    result = []
    for item in step.get('observation', {}).get('results', []):
        value = item.get('content', '')
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict) and 'output' in decoded:
                value = str(decoded['output'])
                if 'returncode' in decoded:
                    value = f'Exit code: {decoded["returncode"]}\n' + value
        except (ValueError, TypeError):
            pass
        result.append(value)
    return '\n'.join(result)


def step_commands(step):
    result = []
    for tool in step.get('tool_calls', []):
        args = tool.get('arguments', {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {'command': args}
        result.append(str(args.get('command', json.dumps(args, ensure_ascii=False))))
    return '\n'.join(result)


def check_runtime(page):
    require(len(page.ids) == len(set(page.ids)), 'Duplicate HTML IDs')
    for reference in page.references:
        value = reference['value']
        require(value.startswith('#'), f'Non-self-contained HTML resource/link: {value}')
        require(value[1:] in page.ids, f'Missing local fragment: {value}')
    visible = '\n'.join(page.visible)
    for term in ('冻结的旧审查', '冻结旧审查', '修订前审查', '旧审查', 'Frozen previous review'):
        require(term not in visible, f'Historical review text rendered: {term}')
    css = '\n'.join(page.styles)
    require(not re.search(r'@import\b|url\s*\(', css, re.I), 'External CSS resource mechanism')
    scripts = [s['text'] for s in page.scripts if s['attrs'].get('type') in (None, '', 'text/javascript', 'application/javascript')]
    require(scripts, 'No embedded runtime JavaScript')
    runtime = '\n'.join(scripts)
    network = r'\b(?:fetch|import|require|importScripts)\s*\(|\bimport\s+[\w{*]|\b(?:XMLHttpRequest|WebSocket|EventSource|Worker)\s*\('
    require(not re.search(network, runtime), 'Runtime contains network/import dependencies')
    require(not re.search(r'https?://|(?:cdnjs|jsdelivr|unpkg)\.', runtime, re.I), 'Runtime refers to a remote host/CDN')
    node = shutil.which('node')
    require(node is not None, 'node is required to syntax-check embedded JavaScript')
    with tempfile.TemporaryDirectory(prefix='deepswe-portable-audit-') as directory:
        path = Path(directory) / 'runtime.js'
        path.write_text(runtime)
        checked = subprocess.run([node, '--check', str(path)], capture_output=True, text=True)
        require(checked.returncode == 0, f'JavaScript syntax error: {checked.stderr}')
    require('language-toggle' in page.ids, 'Missing one-click language control')
    require('data-lang="zh"' in DEST.read_text() and 'data-lang="en"' in DEST.read_text(), 'Missing bilingual UI')
    return {'inline_runtime_scripts': len(scripts), 'external_resources': 0, 'javascript_syntax': 'passed'}


def audit():
    rows = [json.loads(line) for line in (STUDY / 'reviews.jsonl').read_text().splitlines()]
    require(len(rows) == 211 and len({r['trial'] for r in rows}) == 211, 'Reference cohort must contain 211 unique trials')
    require(len({r['task'] for r in rows}) == 90, 'Reference cohort must contain 90 tasks')
    presentation = [item for path in sorted(CONTENT.glob('content_*.json')) for item in read(path)]
    require(len(presentation) == 211, 'Presentation must contain 211 rows')
    by_trial = {item['trial']: item for item in presentation}
    require(len(by_trial) == 211, 'Duplicate presentation trial')
    visual_rows = [item for path in sorted(VISUALS.glob('visuals_*.json')) for item in read(path)]
    visual_by_trial = {item['trial']:item for item in visual_rows}
    require(len(visual_rows) == len(visual_by_trial) == 211, 'Expected 211 authored visual records')
    page = Page(DEST.read_text())
    data, packaging = unpack_payload(page)
    check_keys(data)
    cases, tasks = data['cases'], data['tasks']
    require(set(cases) == {r['trial'] for r in rows}, 'Embedded trial IDs differ from the cohort')
    require(set(tasks) == {r['task'] for r in rows}, 'Embedded tasks differ from the cohort')
    require(len(page.cards) == 211 and {c['id'] for c in page.cards} == set(cases), 'Trial cards differ from embedded cases')
    cards = {c['id']: c for c in page.cards}
    hashes_checked, steps_checked, complete_files = 0, 0, 0
    visual_checks = []
    for task, item in tasks.items():
        path = EVIDENCE / 'evaluation_tests' / task / 'test.patch'
        require(item['test_patch'].encode() == path.read_bytes(), f'{task}: incomplete/changed evaluation test patch')
        complete_files += 1
    for row in rows:
        trial = row['trial']
        case, text = cases[trial], by_trial[trial]
        require(case['trial'] == trial and case['n'] == row['n'], f'{trial}: identity changed')
        for key in ('task', 'repository', 'language', 'decision', 'metric'):
            require(case[key] == row[key], f'{trial}: {key} changed')
        require(cards[trial]['data-status'] == row['decision'], f'{trial}: card decision changed')
        require(cards[trial]['data-positive'] == str(row['positive_under_current_definition']).lower(), f'{trial}: card positivity changed')
        require(case['metrics'] == row['original_metrics'], f'{trial}: original metrics changed')
        raw = ROOT / row['raw_evidence_directory']
        metadata = read(raw / 'metadata.json')
        require(case['metrics'] == {k: metadata[k] for k in METRICS}, f'{trial}: metrics differ from raw metadata')
        for lang in ('zh', 'en'):
            require(set(case['analysis'][lang]) == FIELDS, f'{trial}: incomplete {lang} analysis')
            require(case['analysis'][lang] == text[lang], f'{trial}: {lang} differs from presentation')
            require(case['overview'][lang] == text['overview'][lang] and bool(case['overview'][lang].strip()), f'{trial}: incomplete {lang} overview')
            for key in FIELDS:
                require(isinstance(case['analysis'][lang][key], str), f'{trial}: non-text {lang}.{key}')
                require(bool(case['analysis'][lang][key]) == bool(row[key]), f'{trial}: {lang}.{key} missing or invented')
        for field, filename in (('issue', 'instruction.md'), ('patch', 'model.patch')):
            require(case[field].encode() == (raw / filename).read_bytes(), f'{trial}: incomplete/changed {field}')
            complete_files += 1
        sources = {name: raw / name for name in ('instruction.md', 'model.patch', 'trajectory.json')}
        sources.update({name: EVIDENCE / 'evaluation' / trial / name for name in ('ctrf.json', 'reward.json', 'test-stdout.txt')})
        sources['test.patch'] = EVIDENCE / 'evaluation_tests' / row['task'] / 'test.patch'
        require(set(case['evidence_hashes']) == set(sources), f'{trial}: missing evidence hash')
        for name, path in sources.items():
            require(case['evidence_hashes'][name] == sha(path), f'{trial}: source hash differs for {name}')
            hashes_checked += 1
        trajectory = read(raw / 'trajectory.json')
        steps = {s['step_id']: s for s in trajectory['steps']}
        visual_checks.append(check_visuals(case,visual_by_trial[trial],steps,trial,row['decision']))
        selected = case['validation']['steps']
        require([s['step'] for s in selected] == text['validation_steps'], f'{trial}: selected validation steps changed/omitted')
        for item in selected:
            sid = item['step']
            require(sid in steps, f'{trial}: missing trajectory step {sid}')
            check_clipped(item['commands'], step_commands(steps[sid]), f'{trial}: step {sid} command')
            check_clipped(item['output'], observation_text(steps[sid]), f'{trial}: step {sid} output')
            steps_checked += 1
        patch_parts = {}
        for part in re.split(r'(?=^diff --git )', case['patch'], flags=re.M):
            if part.startswith('diff --git '):
                match = re.search(r' b/(.*)$', part.splitlines()[0])
                if match:
                    patch_parts[match[1]] = part
        focus = case['validation'].get('focus')
        if focus is not None:
            require(focus.get('source') == 'submitted_patch', f'{trial}: unsupported validation focus source')
            require(focus.get('path') in patch_parts, f'{trial}: validation focus file missing from submitted patch')
            check_excerpt(focus['excerpt'], patch_parts[focus['path']], f'{trial}: validation focus {focus["path"]}')
        for item in case['validation']['final_test_excerpts']:
            require(item['path'] in patch_parts, f'{trial}: invented submitted test file')
            check_excerpt(item, patch_parts[item['path']], f'{trial}: submitted test excerpt {item["path"]}')
        ev = case['evaluation']
        tests = read(sources['ctrf.json'])['results']['tests']
        failed = [t for t in tests if t['status'] not in ('passed', 'skipped')]
        require(ev['failure_count'] == len(failed), f'{trial}: failure count changed')
        require(ev['failure_index'] == [{'name': t['name'], 'status': t['status']} for t in failed], f'{trial}: incomplete failure index')
        require(ev['reported_statuses'] == dict(Counter(t['status'] for t in tests)), f'{trial}: reported statuses differ')
        failed_by_name = {t['name']: t for t in failed}
        for failure in ev['focus']:
            require(failure['name'] in failed_by_name, f'{trial}: invented focused failure')
            source = failed_by_name[failure['name']]
            require(failure['status'] == source['status'], f'{trial}: focused status changed')
            check_clipped(failure['message'], source.get('message', ''), f'{trial}: focused error message')
        check_excerpt(ev['test_excerpt'], tasks[row['task']]['test_patch'], f'{trial}: evaluation test excerpt')
        check_excerpt(ev['stdout'], sources['test-stdout.txt'].read_text(errors='replace'), f'{trial}: stdout excerpt')
    require(set(data['labels']) == {r['decision'] for r in rows}, 'Judgment labels do not cover all decisions')
    for decision, label in data['labels'].items():
        require(all(isinstance(label.get(lang), str) and label[lang].strip() for lang in ('zh', 'en')), f'{decision}: incomplete bilingual label')
    runtime = check_runtime(page)
    copies = []
    copy = ROOT / 'experiments/reports/docs' / DEST.name
    if copy.exists():
        require(copy.read_bytes() == DEST.read_bytes(), 'Portable reading copy differs from main HTML')
        copies.append(str(copy.relative_to(ROOT)))
    result = {
        'schema_version': 'deepswe-portable-report-audit.v2',
        'status': 'passed', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'html': str(DEST.relative_to(ROOT)), 'html_sha256': sha(DEST), 'html_bytes': DEST.stat().st_size,
        'trials': len(cases), 'tasks': len(tasks), 'repositories': len({r['repository'] for r in rows}),
        'decisions': dict(Counter(r['decision'] for r in rows)),
        'original_metrics_and_decisions_unchanged': True,
        'languages': ['zh', 'en'], 'complete_source_files_verified': complete_files,
        'evidence_hashes_verified': hashes_checked, 'validation_steps_verified': steps_checked,
        'gap_tables_verified': len(visual_checks),
        'authored_trajectory_events_verified': sum(item['events'] for item in visual_checks),
        'verbatim_trajectory_quotes_verified': sum(item['quotes'] for item in visual_checks),
        'table_column_counts': dict(Counter(item['columns'] for item in visual_checks)),
        'table_layouts': dict(Counter(item['layout'] for item in visual_checks)),
        'evaluation_excerpts_match_primary_sources': True,
        'historical_review_fields_embedded': False, 'historical_review_links': 0,
        'reading_copies_byte_equal': copies, **runtime, **packaging,
        'limitations': ['No independent semantic re-labeling.', 'No coding-agent rerun or measured F2P/P2P gain.', 'No browser rendering or interaction test is implied by this structural audit.'],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    try:
        result = audit()
    except Exception as exc:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps({'schema_version': 'deepswe-portable-report-audit.v2', 'status': 'failed', 'error': str(exc)}, ensure_ascii=False, indent=2) + '\n')
        raise
    print(json.dumps({k: result[k] for k in ('status', 'trials', 'tasks', 'validation_steps_verified', 'external_resources', 'javascript_syntax')}, ensure_ascii=False))
