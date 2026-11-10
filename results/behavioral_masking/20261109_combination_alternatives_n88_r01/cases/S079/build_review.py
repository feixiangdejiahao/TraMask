import json
from pathlib import Path

directory = Path(__file__).parent
case = json.loads((directory / 'case.json').read_text())
failures = json.loads((directory / 'evaluation_failures.json').read_text())['failed_tests']
status = json.loads((directory / 'reading_status.json').read_text())
inventory = json.loads(Path(case['repository_materials']).read_text())
entries = {e['path']: e for e in inventory['entries'] if e['status'] == 'stored'}
cas = Path(case['repository_materials']).parents[2] / 'cas/sha256'


def command(step, quote):
    return {'step': step, 'call': 0, 'channel': 'command', 'quote': quote}


def output(step, quote):
    return {'step': step, 'call': 0, 'channel': 'output', 'quote': quote}


def reasoning(step, quote):
    return {'step': step, 'channel': 'reasoning', 'quote': quote}


def repo(name, quote):
    sha = entries[name]['sha256']
    return {'channel': 'repo', 'path': str(cas / sha[:2] / sha), 'quote': quote}


materials = []


def material(mid, kind, availability, unit, gaps, refs, origin='agent_authored', artifact='', symbol=''):
    materials.append({'id': mid, 'kind': kind, 'origin': origin, 'availability': availability,
                      'unit': unit, 'supports': gaps, 'artifact': artifact, 'symbol': symbol, 'refs': refs})


material('E1', 'agent_validation', 'executed_pass', 'TestStyleTruncate/preserve resets: Bold Style, embedded reset, correct reopened internal Bold through Truncate', ['G1:preserve_fixture'],
         [command(27, 'style: String("Hello \\x1b[0mWorld").Bold().PreserveResets(),'), output(27, 'ok  \tgithub.com/muesli/termenv\t0.027s')], artifact='truncate_test.go', symbol='TestStyleTruncate/preserve resets')
material('E2', 'temporary_probe', 'executed_output', '/tmp/check/main.go style preserve probe; reopened Bold observed under Truncate', ['G1:preserve_fixture'],
         [command(24, 'p("style preserve", termenv.String('), output(24, r'style preserve: "\x1b[1mHello \x1b[0m\x1b[1mWorld')], artifact='/tmp/check/main.go', symbol='style preserve')
material('E3', 'temporary_probe', 'executed_pass', '/tmp/final_check.go style preserve hard comparison; runs again after commit', ['G1:preserve_fixture'],
         [command(44, 'check("style preserve",'), output(44, 'PASS style preserve'), output(52, 'ALL CHECKS PASSED')], artifact='/tmp/final_check.go', symbol='style preserve')
material('E4', 'agent_validation', 'executed_pass', 'ansi TestTruncateANSI/preserve resets: exact internal reset followed by reopened red and continued text', ['G1:reset_input_and_oracle'],
         [command(26, 'name: "preserve resets",'), command(26, r'want: "\x1b[31mHello \x1b[0m\x1b[31mWo\x1b[0m",'), output(26, '--- PASS: TestTruncateANSI/preserve_resets')], artifact='ansi/ansi_test.go', symbol='TestTruncateANSI/preserve resets')
material('E5', 'agent_validation', 'executed_pass', 'ansi TestTruncateANSIEdgeCases/preserve multiple resets: AA/BB/CC and exact reopening at each internal reset', ['G1:reset_input_and_oracle'],
         [command(33, 'name: "preserve multiple resets",'), command(33, r'want: "\x1b[31mAA\x1b[0m\x1b[31mBB\x1b[0m\x1b[31mCC\x1b[0m",'), output(33, 'ok  \tgithub.com/muesli/termenv/ansi\t0.009s')], artifact='ansi/ansi_test.go', symbol='TestTruncateANSIEdgeCases/preserve multiple resets')
material('E6', 'temporary_probe', 'executed_output', '/tmp/check/main.go ANSI preserve operation with actual correct reopened red output', ['G1:reset_input_and_oracle'],
         [command(24, 'p("preserve", ansi.TruncateANSI('), output(24, r'preserve: "\x1b[31mHello \x1b[0m\x1b[31mWo\x1b[0m"')], artifact='/tmp/check/main.go', symbol='preserve')
material('E7', 'temporary_probe', 'executed_pass', '/tmp/final_check.go ANSI preserve hard comparison', ['G1:reset_input_and_oracle'],
         [command(44, 'check("truncate preserve",'), output(44, 'PASS truncate preserve')], artifact='/tmp/final_check.go', symbol='truncate preserve')
material('E8', 'agent_validation', 'executed_pass', 'TestOutputStringInheritsPreserveResets: Output default true, same returned Bold Style and embedded reset, checked through Truncate only', ['G1:output_default_fixture'],
         [command(27, 'func TestOutputStringInheritsPreserveResets(t *testing.T)'), command(27, 'got := o.String("Hello \\x1b[0mWorld").Bold().Truncate(100, TruncateOptions{})'), output(27, 'ok  \tgithub.com/muesli/termenv\t0.027s')], artifact='truncate_test.go', symbol='TestOutputStringInheritsPreserveResets')
material('E9', 'temporary_probe', 'executed_output', '/tmp/check/main.go output-created Style inherits preserve true and correct internal reopen through Truncate', ['G1:output_default_fixture'],
         [command(24, 'p("out string inherits",'), output(24, r'out string inherits: "\x1b[1mHello \x1b[0m\x1b[1mWorld')], artifact='/tmp/check/main.go', symbol='out string inherits')
material('E10', 'temporary_probe', 'executed_pass', '/tmp/final_check.go output-created Style with hard expected reopening, still tested via Truncate', ['G1:output_default_fixture'],
         [command(44, 'check("output string inherits",'), output(44, 'PASS output string inherits')], artifact='/tmp/final_check.go', symbol='output string inherits')
material('E11', 'agent_validation', 'executed_pass', 'TestOutputTruncate default preserve true and exact reopened red expected value', ['G1:output_default_and_reset'],
         [command(27, 'preserve := NewOutput(io.Discard, WithProfile(ANSI), WithPreserveResets(true))'), command(27, 'if got := preserve.Truncate('), output(27, 'ok  \tgithub.com/muesli/termenv\t0.027s')], artifact='truncate_test.go', symbol='TestOutputTruncate/preserve')
material('E12', 'temporary_probe', 'executed_output', '/tmp/check/main.go Output.Truncate default true and correct reopened red print', ['G1:output_default_and_reset'],
         [command(24, 'p("out preserve",'), output(24, r'out preserve: "\x1b[31mHello \x1b[0m\x1b[31mWo\x1b[0m"')], artifact='/tmp/check/main.go', symbol='out preserve')
material('E13', 'temporary_probe', 'executed_pass', '/tmp/final_check.go Output.Truncate default true hard check', ['G1:output_default_and_reset'],
         [command(44, 'check("output preserve",'), output(44, 'PASS output preserve')], artifact='/tmp/final_check.go', symbol='output preserve')
material('E14', 'agent_validation', 'executed_pass', 'TestOutputTemplateFuncsPropagatesDefault: Output default true, template execution and exact byte equality, but helper is Truncate', ['G1:template_default_harness'],
         [command(27, 'func TestOutputTemplateFuncsPropagatesDefault(t *testing.T)'), command(27, 'Funcs(o.TemplateFuncs())'), output(27, 'ok  \tgithub.com/muesli/termenv\t0.027s')], artifact='truncate_test.go', symbol='TestOutputTemplateFuncsPropagatesDefault')
material('E15', 'temporary_probe', 'executed_output', '/tmp/check/tpl.go Output template + default preserve + reset input, printed correct Truncate helper output', ['G1:template_default_harness'],
         [command(31, 'Funcs(o.TemplateFuncs()).Parse('), output(31, r'output tpl => "\x1b[31mHello \x1b[0m\x1b[31mWo\x1b[0m"')], artifact='/tmp/check/tpl.go', symbol='output tpl')
material('E16', 'temporary_probe', 'executed_pass', '/tmp/final_check.go template default preserve with correct hard expected bytes, helper still Truncate', ['G1:template_default_harness'],
         [command(44, 'check("template preserve default",'), output(44, 'PASS template preserve default'), output(52, 'PASS template preserve default')], artifact='/tmp/final_check.go', symbol='template preserve default')
material('E17', 'repo_test', 'executed_pass', 'Original TestTemplateHelpers table: Bold/Faint/etc and nested Underline(Bold), buffer execution and String-derived equality', ['G1:ordinary_template_consumer'],
         [output(6, 'Template: fmt.Sprintf(basetpl, "Bold"),'), output(6, 'Template: fmt.Sprintf(wraptpl, "Underline", "Bold"),'), repo('termenv_test.go', 'func TestTemplateHelpers(t *testing.T)'), output(39, 'ok  \tgithub.com/muesli/termenv\t0.029s')], origin='repo_preexisting', artifact='termenv_test.go', symbol='TestTemplateHelpers')
material('E18', 'repo_test', 'executed_pass', 'Original TestRendering String consumer, multiple enclosing styles, hard explicit byte equality; ASCII color/no-style control', ['G1:ordinary_style_consumer', 'G2:style_builder'],
         [output(6, 'func TestRendering(t *testing.T)'), output(6, 'if out.String() != exp {'), output(39, 'ok  \tgithub.com/muesli/termenv\t0.029s')], origin='repo_preexisting', artifact='termenv_test.go', symbol='TestRendering')
material('E19', 'repo_test', 'executed_pass', 'Original TestTemplateFuncs and templatehelper.tpl/golden: all style helpers and byte comparator across four profiles', ['G1:ordinary_template_consumer'],
         [output(6, 'func TestTemplateFuncs(t *testing.T)'), output(14, '{{ Bold "Bold" }}'), output(14, '{{ Foreground "#00ffff" (Background "#ff00ff" "Cyan on Magenta Bg") }}'), output(39, 'ok  \tgithub.com/muesli/termenv\t0.029s')], origin='repo_preexisting', artifact='templatehelper_test.go + testdata/templatehelper.tpl', symbol='TestTemplateFuncs')
material('E20', 'repo_test', 'repo_unseen', 'Original TestStyles exact green32 String render and full byte equality; source fell in original step6 output elision, case CAS retains it', ['G1:ordinary_style_consumer'],
         [repo('termenv_test.go', 'func TestStyles(t *testing.T)'), repo('termenv_test.go', r'exp := "\x1b[32mfoobar\x1b[0m"')], origin='repo_preexisting', artifact='termenv_test.go', symbol='TestStyles')
material('E21', 'repo_test', 'executed_pass', 'Original TestStyleWidth: reusable Hello World Style, Bold/Italic/color mutations and hard width11 control', ['G1:style_builder', 'G2:style_builder'],
         [output(6, 'func TestStyleWidth(t *testing.T)'), output(6, 's := String("Hello World")'), output(39, 'ok  \tgithub.com/muesli/termenv\t0.029s')], origin='repo_preexisting', artifact='style_test.go', symbol='TestStyleWidth')
material('E22', 'implementation', 'read_only', 'Legacy and final Style.String delegates to Styled(s); Styled ignores preserve flag. Public receiver/consumer linkage and profile behavior', ['G1:render_interface', 'G2:style_interface'],
         [output(4, 'return t.Styled(t.string)'), command(18, 'func (t Style) Styled(s string) string {'), command(18, 'return fmt.Sprintf("%s%sm%s%sm", CSI, seq, s, CSI+ResetSeq)')], artifact='style.go', symbol='Style.String/Styled')
material('E23', 'implementation', 'read_only', 'Output template factories call str(...).String through styleFunc; Output.String propagates flag but final consumer does not read it', ['G1:template_consumer_connection'],
         [command(21, 'style.preserveResets = o.preserveResets'), command(22, 'return templateFuncs(o.Profile, o.String, o.Truncate)'), command(22, 'return f(s).String()')], artifact='output.go + templatehelper.go', symbol='Output.String/templateFuncs/styleFunc')
material('E24', 'agent_validation', 'executed_pass', 'Tokenize mixed reset case ESC[1;0m with exact TokenReset expected kind and named PASS', ['G1:compound_reset_input'],
         [command(26, 'name: "mixed reset",'), command(26, r'in:   "\x1b[1;0m",'), output(26, '--- PASS: TestTokenize/mixed_reset')], artifact='ansi/ansi_test.go', symbol='TestTokenize/mixed reset')
material('E25', 'agent_validation', 'executed_pass', 'TruncateANSI zero max plain Hello: input no control sequences, explicit empty oracle and named PASS', ['G3:zero_width'],
         [command(26, 'name: "zero max",'), command(26, 'in:   "Hello",\n\t\t\tmax:  0,'), output(26, '--- PASS: TestTruncateANSI/zero_max')], artifact='ansi/ansi_test.go', symbol='TestTruncateANSI/zero max')
material('E26', 'agent_validation', 'executed_pass', 'TruncateANSI hyperlink close at width100: open unclosed link, Hello, exact added close oracle', ['G3:hyperlink_state_and_close'],
         [command(26, 'name: "hyperlink close",'), command(26, r'want: "\x1b]8;;http://example.com\x1b\\Hello\x1b]8;;\x1b\\",'), output(26, '--- PASS: TestTruncateANSI/hyperlink_close')], artifact='ansi/ansi_test.go', symbol='TestTruncateANSI/hyperlink close')
material('E27', 'agent_validation', 'executed_pass', 'TruncateANSIEdgeCases hyperlink at width5 actual cut, exact open/Hello/close expected', ['G3:hyperlink_state_and_close'],
         [command(33, 'name: "hyperlink preserved when truncated",'), command(33, r'in:   "\x1b]8;;http://example.com\x1b\\Hello World",'), output(33, 'ok  \tgithub.com/muesli/termenv/ansi\t0.009s')], artifact='ansi/ansi_test.go', symbol='TestTruncateANSIEdgeCases/hyperlink preserved when truncated')
material('E28', 'temporary_probe', 'executed_output', '/tmp/check/main.go unclosed hyperlink width100 -> retained open/text/added close, printed', ['G3:hyperlink_state_and_close'],
         [command(24, 'p("link", ansi.TruncateANSI('), output(24, r'link: "\x1b]8;;http://example.com\x1b\\Hello\x1b]8;;\x1b\\"')], artifact='/tmp/check/main.go', symbol='link')
material('E29', 'temporary_probe', 'executed_pass', '/tmp/final_check.go unclosed hyperlink width100 hard expected close', ['G3:hyperlink_state_and_close'],
         [command(44, 'check("truncate link",'), output(44, 'PASS truncate link')], artifact='/tmp/final_check.go', symbol='truncate link')
material('E30', 'implementation', 'read_only', 'TruncateANSI early max<=0 return precedes Tokenize and hyperlink state tracking; final47 source retains it', ['G3:boundary_order'],
         [command(17, 'if max <= 0 {\n\t\treturn ""'), output(47, 'if max <= 0 {\n\t\treturn ""')], artifact='ansi/ansi.go', symbol='TruncateANSI')
material('E31', 'agent_validation', 'executed_pass', 'Original TestStyleTruncate/ascii no tail correct full row: Hello World width5 tail..., expected Hello; passed27 and fresh39', ['G2:complete_historical_oracle_and_stimulus'],
         [command(27, 'name:  "ascii no tail",'), command(27, 'want:  "Hello",'), output(27, 'ok  \tgithub.com/muesli/termenv\t0.027s'), output(39, 'ok  \tgithub.com/muesli/termenv\t0.029s')], artifact='truncate_test.go', symbol='TestStyleTruncate/ascii no tail (before40)')
material('E32', 'agent_validation', 'executed_pass', 'Revised40 TestStyleTruncate/ascii row keeps target stimulus but changes expected to full Hello World; source and oracle changed together', ['G2:final_stimulus_wrong_check'],
         [command(40, 'want:  "Hello World",'), output(40, 'ok  \tgithub.com/muesli/termenv\t0.024s')], artifact='truncate_test.go', symbol='TestStyleTruncate/ascii no tail (after40)')
material('E33', 'temporary_probe', 'executed_output', '/tmp/check/main.go same ASCII width5/tail probe after correct25 production update prints Hello', ['G2:complete_historical_observation'],
         [command(24, 'p("style ascii", termenv.Ascii.String("Hello World").Bold().Truncate(5,'), output(25, 'style ascii: "Hello"')], artifact='/tmp/check/main.go', symbol='style ascii (after25)')
material('E34', 'temporary_probe', 'executed_output', '/tmp/check/main.go original ASCII probe24 printed full Hello World, before25 temporary correction', ['G2:initial_wrong_observation'],
         [command(24, 'p("style ascii",'), output(24, 'style ascii: "Hello World"')], artifact='/tmp/check/main.go', symbol='style ascii (before25)')
material('E35', 'temporary_probe', 'executed_pass', '/tmp/final_check.go later ASCII check hardcodes full Hello World; survives after authored test deletion', ['G2:final_stimulus_wrong_check'],
         [command(44, 'check("style ascii",'), command(44, 'Truncate(5, termenv.TruncateOptions{Tail: "..."}), "Hello World")'), output(44, 'PASS style ascii')], artifact='/tmp/final_check.go', symbol='style ascii')
material('E36', 'agent_validation', 'executed_pass', 'TruncateANSI plain no-tail width5 on Hello World, hard expected Hello and PASS', ['G2:plain_width_oracle'],
         [command(26, 'name: "plain",'), command(26, 'want: "Hello",'), output(26, '--- PASS: TestTruncateANSI/plain')], artifact='ansi/ansi_test.go', symbol='TestTruncateANSI/plain')
material('E37', 'agent_validation', 'executed_pass', 'TestOutputTruncate ASCII profile strips raw ANSI and uses width5/tail... expected He...', ['G2:ascii_output_context'],
         [command(27, 'ascii := NewOutput(io.Discard, WithProfile(Ascii))'), command(27, 't.Errorf("Ascii output Truncate = %q", got)'), output(27, 'ok  \tgithub.com/muesli/termenv\t0.027s')], artifact='truncate_test.go', symbol='TestOutputTruncate/Ascii')
material('E38', 'issue_or_documentation', 'read_only', 'Task preserve-all-rendering scope, ASCII truncation without tail, zero-width atomic controls and hyperlink closure', ['G1:contract', 'G2:contract', 'G3:contract'],
         [{'channel': 'issue', 'path': case['issue'], 'quote': 'When preserve-resets is enabled, re-open the enclosing style after each reset run.'},
          {'channel': 'issue', 'path': case['issue'], 'quote': 'Under Ascii, Style.Truncate returns plain text without tail; Output.Truncate returns text with tail; no ANSI emitted.'},
          {'channel': 'issue', 'path': case['issue'], 'quote': 'Truncation must never split CSI/OSC sequences; they have zero visible width.'}], origin='issue', artifact='instruction.md')
material('E39', 'reasoning', 'reasoning_only', 'Earlier correct explicit ASCII semantics and concrete hidden-test sketch max5->Hello; later40 contradicts it', ['G2:correct_historical_oracle'],
         [reasoning(25, 'The text itself should still be truncated.'), reasoning(25, 'I now lean toward "truncated plain text without tail".')], artifact='trajectory reasoning', symbol='step25 ASCII interpretation')

recipes = []


def recipe(rid, gap, qualification, slots, compatibility, additions):
    recipes.append({'id': rid, 'gap': gap, 'qualification': qualification,
                    'slots': [{'role': role, 'alternatives': options} for role, options in slots],
                    'forbidden_pairs': [], 'compatibility': compatibility, 'semantic_additions': additions})


recipe('R1', 'G1', 'requires_transfer', [
    ('preserving Style plus reset input and known internal reopening relation', [[m] for m in ['E1','E2','E3','E8','E9','E10']]),
    ('ordinary renderer API link', [['E22']]), ('applicable contract', [['E38']])],
    'Retain the exact same Style, flag, input and internal reset. Replace its final Truncate call by String(), or use the equivalent Styled(input) public path from E22. Check reopening immediately after the internal reset, using the fixture known reopening relation and the same enclosing SGR. Do not copy the Truncate-specific redundant end resets as a byte-for-byte renderer oracle. Output-created variants retain the same Output and its true default.',
    ['Transfer the already checked internal reset/reopen relation to the ordinary renderer. Add a decisive internal-boundary check for print-only probes; no new intended reset relation.'])
recipe('R2', 'G1', 'requires_transfer', [
    ('legacy ordinary Style builder/observer', [[m] for m in ['E18','E20','E21']]),
    ('reset input and reopening relation', [[m] for m in ['E4','E5','E6','E7']]),
    ('public renderer and preserve flag interface', [['E22','E38']])],
    'Use a non-Ascii legacy Style, insert the known internal reset between two nonempty text segments, enable its PreserveResets flag, and render normally. Bind the expected reopen to the actual enclosing Style sequence rather than the red literal in the ANSI helper example. E21 supplies construction only, so transfer a concrete equality/adjacency check from the reset fixture. E20 is repository source unseen by the Agent. All choices retain visible continuation after the reset.',
    ['Compose the legacy renderer with an internal-reset fixture and enable the existing feature flag.'])
recipe('R3', 'G1', 'requires_transfer', [
    ('Output preserve-default reset fixture', [[m] for m in ['E8','E9','E10','E11','E12','E13']]),
    ('Output->Style and ordinary-render linkage', [['E22','E23']]), ('contract', [['E38']])],
    'Retain one non-Ascii Output with preserve true and its reset-containing input. Obtain its Style with Output.String, add an enclosing Bold or Foreground style, and call Styled on that same input. Existing Output.Truncate variants need this consumer transfer; Output.String variants keep their receiver. Require reopening at the internal reset using its known relation. Do not test a fresh default-false Output.',
    ['Transfer the defaulted preservation scenario from Truncate to the ordinary renderer; add enclosing Style only in raw Output.Truncate variants.'])
recipe('R4', 'G1', 'requires_transfer', [
    ('defaulted Output template execution with reset data', [[m] for m in ['E14','E15','E16']]),
    ('existing ordinary style-helper template', [['E17'],['E19']]),
    ('known reset/reopen observation', [[m] for m in ['E4','E5','E6','E7']]),
    ('consumer connection and contract', [['E23','E38']])],
    'Keep Output.TemplateFuncs on the same preserve-true Output and buffer execution scaffold, but invoke Bold/Foreground or another existing enclosing-style helper on reset-containing data instead of Truncate. Bind reopen to that helper outer style. Existing inner red may be removed only by using the fixture content after its leading open; alternatively retain it and observe outer Bold reopening, without assuming the inner color survives. Rebuild expected bytes from the known relation, never from the buggy Style.String as reference.',
    ['Transfer to an ordinary style-helper consumer; adapt template data and its explicit known reset-boundary oracle.'])
recipe('R5', 'G1', 'requires_transfer', [
    ('ordinary preserving Style fixture', [[m] for m in ['E1','E2','E3','E8','E9','E10']]),
    ('executed compound reset classification', [['E24']]),
    ('renderer and contract', [['E22','E38']])],
    'Replace the fixture ordinary internal ESC[0m with the actually classified ESC[1;0m. Render via Styled/String, not Truncate, and require the same enclosing style reopened after it. Presence of any zero parameter supplies the same task reset condition. The official extra31 parameter is unnecessary to demonstrate this ignored-flag behavior.',
    ['Transfer an executed compound-reset stimulus to the renderer. This preserves the task reset semantics; no new reset type is invented.'])
recipe('R6', 'G2', 'direct', [('earlier complete correct ASCII test version', [['E31']])],
    'Restore the pre40 TestStyleTruncate row and its Hello expected value unchanged; input Hello World, width5, Tail... and ASCII Style remain identical. It passed on earlier implementation; final source return-full behavior contradicts the same row. The complete historical test table is available in step27.', [])
recipe('R7', 'G2', 'requires_transfer', [('earlier correct executed ASCII observation', [['E33']])],
    'Replay the same ASCII call and compare its observed string to the earlier Hello result. Add an executable comparison to the old print-only probe; the expected string and full stimulus already occur together in history.', ['Turn an observed correct result into a hard assertion.'])
recipe('R8', 'G2', 'requires_transfer', [
    ('later explicit ASCII stimulus', [['E32'],['E35'],['E34']]),
    ('correct width relation', [['E36','E39'],['E33']])],
    'Keep the exact Hello World/width5/Tail... ASCII call, replacing only the full-string expected value with earlier Hello. E36+E39 combines an executed plain-width oracle with the earlier explicit rule that Style under Ascii still truncates and omits tail. E33 supplies the same ASCII result directly. These are logical alternatives to retaining the old full test, not new setup edits.',
    ['Restore the correct historical expected value, and add an assertion where the base only printed.'])
recipe('R9', 'G2', 'requires_transfer', [
    ('executed plain no-tail width result', [['E36']]),
    ('ASCII Output construction', [['E37']]), ('Style builder and API', [['E21','E22']]),
    ('ASCII distinction', [['E38']])],
    'Obtain the ASCII Output Style through Output.String, retain its Hello World text and requested width5, add Bold and a configured Tail..., then truncate on the Style. Transfer plain Hello from E36, using the task explicit distinction that the Style omits the tail while Output applies it. Do not copy E37 He... as the Style expected result.',
    ['Compose existing ASCII construction with the Style consumer and the no-tail contract.'])
recipe('R10', 'G3', 'requires_oracle_inference', [
    ('executed zero budget', [['E25']]),
    ('executed open hyperlink and close observation', [[m] for m in ['E26','E27','E28','E29']]),
    ('boundary and task text', [['E30','E38']])],
    'Keep one complete OSC8 opening and visible text from the hyperlink fixture; set width to the existing zero budget. If the intended policy retains zero-width leading controls, expected output is that opening followed by a matching close and no visible text. The early-return implementation instead emits empty. This recipe is conditional on the verifier sequence-retention convention, not proof that empty output violates atomicity or closure.',
    ['Infer the stronger policy that width0 must retain the leading OSC even when no visible text is emitted; the task does not state that policy explicitly.'])
recipe('R11', 'G3', 'incomplete', [('plain zero-budget test alone', [['E25']])],
    'Plain Hello at width0 has no open hyperlink or control-sequence retention oracle. It cannot establish the failing OSC expectation.', ['OSC input and retention policy are absent.'])

review = {
    'case_id': 'S079', 'reviewer': '/root',
    'full_read': {'line_ranges': status['fulltext_read_ranges'], 'steps': 53, 'unread': [], 'metadata_read': True,
                  'original_observation_elisions': [4,6],
                  'reread_note': 'Truncated combined first read was replaced by complete1-1500;3001-3750 and5501-6250 were reread in375-line blocks. All retained fulltext11874 lines read.'},
    'evaluation_families': [
        {'id': 'G1', 'failed_tests': [f['name'] for f in failures if 'PreserveResets_' in f['name']],
         'contract': 'PreserveResets must reopen the enclosing style after an internal reset in ordinary rendering as well as truncation; Output default and all template helpers inherit it.',
         'missing_joint_test': 'Create non-Ascii Bold/green Style with preserve enabled, then call Styled on a+reset+b; require enclosing open immediately after the internal reset. Repeat through Output.String with default true, compound reset containing0, and Output.TemplateFuncs Bold helper. Four failed names are the same ignored-flag consumer family.',
         'classification': 'untested_interaction', 'verifier_validity': 'supported', 'joint_attempt': 'absent',
         'required_components': ['enclosing Style', 'enabled preserve flag', 'internal reset followed by visible continuation', 'ordinary Styled/String/template consumer', 'same enclosing-style reopening oracle'],
         'evaluation_boundary': 'ReappliesAfterReset stops at its first regular reset failure; its later short-reset/non-reset checks are unreached. Other three failed functions separately execute their named variants. Source propagates Output flag but Styled never reads it.'},
        {'id': 'G2', 'failed_tests': [f['name'] for f in failures if 'MarsAscii_' in f['name']],
         'contract': 'Style.Truncate still honors the requested width under Ascii and omits the configured tail; disabling ANSI styling does not cancel truncation.',
         'missing_joint_test': 'Original historical Ascii.String(Hello World).Bold().Truncate(5,Tail...) must remain Hello. The verifier equivalent abcdef/width3 must be abc. The exact historical semantic witness already existed and passed; restore its old oracle on the final source.',
         'classification': 'weakened_oracle', 'verifier_validity': 'supported', 'joint_attempt': 'weakened',
         'required_components': ['Ascii Style', 'text longer than width', 'configured tail omitted', 'correct prefix expected'],
         'evaluation_boundary': 'Verifier first fails Style resultabcdef!=abc; later ANSI absence and Output.Truncate assertions are unreached. No additional Output failure claimed.'},
        {'id': 'G3', 'failed_tests': [f['name'] for f in failures if 'WhenWidthZero' in f['name']],
         'contract': 'Task requires atomic CSI/OSC, zero visible width and closing open OSC8. Verifier additionally requires retaining an opening/closing pair when width0 emits no visible characters.',
         'missing_joint_test': 'Combine open OSC8 + visible Z with width0; verify no broken controls (empty passes), then the additional expected open+close equality (empty fails).',
         'classification': 'verifier_disputed', 'verifier_validity': 'disputed', 'joint_attempt': 'absent',
         'required_components': ['open OSC8 before text', 'zero budget', 'decision to retain zero-width prefix', 'matching closure equality'],
         'validity_explanation': 'Dropping both complete control sequences emits no split CSI/OSC and no open hyperlink. The statement that controls have zero visible width does not explicitly require retaining them under a zero budget. Observed mismatch is real; a harmful behavior is not independently established.'}
    ],
    'materials': materials, 'recipes': recipes,
    'agent_process': {
        'joint_attempt': 'weakened', 'forgetting_assessment': 'counterevidence',
        'explanations': [
            {'label': 'Feature scope deliberately limited to Truncate', 'support': 'direct',
             'interpretation': 'Agent repeatedly explicitly excludes String rendering from PreserveResets, and accepts inert propagation to ordinary template helpers. This is a scope interpretation decision, not missing recall of the flag or reset rule.',
             'refs': [reasoning(33, 'No — String just renders; preserve-resets only affects Truncate.'), reasoning(40, 'propagation is essentially inert. But it satisfies the letter of the requirement.')]},
            {'label': 'Correct tested ASCII behavior replaced by imagined upstream behavior', 'support': 'direct',
             'interpretation': '25 recognizes truncation must remain and fixes source;27 hardcodes Hello and passes,39 reruns fresh.40 chooses unverified remembered upstream return-full policy and changes source plus expected value together. Correct material was nearby and actively reconsidered.',
             'refs': [reasoning(25, 'The text itself should still be truncated.'), output(25, 'style ascii: "Hello"'), command(27, 'want:  "Hello",'), reasoning(40, 'Let me switch `Style.Truncate` Ascii branch to return `t.string`'), command(40, 'want:  "Hello World",')]},
            {'label': 'Development tests intentionally deleted to avoid hypothetical hidden-test collisions', 'support': 'direct',
             'interpretation': '43 removes both authored test files; later root-suite greens no longer run those rows.44 standalone checks remain, but ASCII expected full text and preservation tests only use Truncate. This is explicit deletion, not absence of historic tests.',
             'refs': [reasoning(43, 'to avoid hidden test collisions'), command(43, 'rm -f ansi/ansi_test.go truncate_test.go'), command(44, 'check("style ascii",'), output(52, 'ALL CHECKS PASSED')]},
            {'label': 'Independent boundary tests substituted for zero-budget hyperlink test', 'support': 'inferred',
             'interpretation': '26 tests plain zero budget and positive-budget hyperlinks in separate rows;33 adds a real cut hyperlink atwidth5, still no zero-budget OSC. Repeated max<=0 assumptions are explicit; the proposed zero-budget expected sequence remains a verifier convention dispute.',
             'refs': [command(26, 'name: "zero max",'), command(26, 'name: "hyperlink close",'), command(33, 'name: "hyperlink preserved when truncated",'), reasoning(16, 'Also, `max <= 0` returns "".')]},
            {'label': 'No observed external stop or unavailable dependency as focal cause', 'support': 'direct',
             'interpretation': 'The optional SSH example cannot download dependencies, but original root tests and standalone checks complete, commit9d1c110 is verified, and53 voluntarily submits. Metadata reports zero configured step/cost/walltime limits and peak126432; length alone does not explain the explicit semantic choices.',
             'refs': [output(41, 'Forbidden'), output(50, '9d1c110'), command(53, 'echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT')]}
        ]},
    'prior_record_corrections': [
        'Old primary packet considered only the historical ASCII Check. Independent full reading confirms that history and adds the four ordinary-render/API-consumer failures and the distinct zero-budget OSC dispute.',
        'The correct ASCII unit is an already complete historical test version, not a newly discovered context-only repair. No new combination is needed to recover that witness.',
        'Expand one selected old ASCII source to multiple test/probe/version alternatives, plus legacy rendering/template tests, Output fixtures and low-level reset behavior for the other failure family.',
        'Original TestStyles source was not visible in retained step6 output; availability is repo_unseen despite an inferred unfiltered-suite membership. Do not relabel it as Agent-read code.'
    ],
    'uncertainties': [
        'No new executions. Direct ASCII restoration and other source-package sufficiency are manual source analyses against existing actual evaluation failure.',
        'G3 exact control-prefix retention atwidth0 is not independently required by the supplied issue. Conditional recipes retain this extra oracle assumption.',
        'Template recipes must use an independent reset/reopen relation, not a buggy Style.String call to manufacture expected output.'
    ]}
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(directory / 'reviewer_notes.txt').write_text(
    '全文11874行/53步及metadata已读。六个evaluation失败重新分三家族。\n'
    'G1四个普通Styled/String/Output/template场景：Agent明确认为PreserveResets只作用Truncate；大量lowlevel与Truncate正确材料可迁移，但没有普通renderer的联合执行。\n'
    'G2 Ascii：25临时修正确，27硬断言Hello且39重跑；40根据想象upstream主动改源码和want为HelloWorld；43又删除所有开发测试，44独立脚本保留错误oracle。不是遗忘。\n'
    'G3 width0 OSC：零宽和hyperlink分别执行，未联合；空输出没拆控制符也不留开启链接，Verifier要求保留open+close有额外约定，单列争议。\n'
    '39个材料单元和11种配方均从本case原始命令、输出、推理或case-specific CAS取得；无跨trial借用。\n')
