import json
from pathlib import Path

directory = Path(__file__).parent
case = json.loads((directory / 'case.json').read_text())
failed = json.loads((directory / 'evaluation_failures.json').read_text())['failed_tests']
inventory = json.loads(Path(case['repository_materials']).read_text())
entries = {e['path']: e for e in inventory['entries']}
cas = Path(case['repository_materials']).parents[2] / 'cas/sha256'


def command(step, quote):
    return dict(step=step, call=0, channel='command', quote=quote)


def output(step, quote):
    return dict(step=step, call=0, channel='output', quote=quote)


def reasoning(step, quote):
    return dict(step=step, channel='reasoning', quote=quote)


def repo(name, quote):
    sha = entries[name]['sha256']
    return dict(channel='repo', path=str(cas / sha[:2] / sha), quote=quote)


materials = []


def material(mid, kind, availability, unit, refs, artifact='', symbol='', origin='agent_authored'):
    materials.append(dict(id=mid, kind=kind, origin=origin, availability=availability,
                          unit=unit, supports=['present_undefined_must_not_default'],
                          refs=refs, artifact=artifact, symbol=symbol))


material('Wmap', 'temporary_probe', 'executed_output',
         'ALREADY JOINT: present map key holding undefined plus default50; actual50 explicitly accepted. Correct task oracle is undefined.',
         [command(174, '{x: a = 50} := {x: undefined}'), output(174, '50'), reasoning(175, 'This matches typical JS destructuring behavior')], '/tmp/f31.tengo')
material('Tarray', 'agent_validation', 'executed_pass',
         'Missing array leaf defaults50 vs present ordinary2 stays2; persistent exact equality helper',
         [command(148, '[a, b = 50] := [1, 2]'), command(148, '[a, b = 50] := [1]'), output(151, 'ok')], 'destructure_test.go', 'TestDestructuringArray')
material('Tmap', 'agent_validation', 'executed_pass',
         'Renamed and shorthand map defaults missing50 vs present2 stays2',
         [command(148, '{x: a = 50} := {x: 2}'), command(148, '{x = 50} := {}'), output(151, 'ok')], 'destructure_test.go', 'TestDestructuringMap')
material('Tlazy', 'agent_validation', 'executed_pass',
         'f() default in array leaf: missing gets100, present1 stays1; return-value oracle, no side-effect counter',
         [command(148, 'f := func() { return 100 }; [a = f()] := [1]; out = a'), command(148, 'f := func() { return 100 }; [a = f()] := []; out = a'), output(151, 'ok')], 'destructure_test.go', 'TestDestructuringDefaultsLazy')
material('Tparam', 'agent_validation', 'executed_pass',
         'Map param x10 returns10 and array-param missing b defaults5. Same callable parameter route; whole argument bare-default undefined is extra feature, not missing leaf.',
         [command(148, 'f := func({x: a}) { return a }; out = f({x: 10})'), command(148, 'f := func([a, b = 5]) { return a + b }; out = f([1])'), output(151, 'ok')], 'destructure_test.go', 'TestDestructuringFunctionParams')
material('Tnested', 'agent_validation', 'executed_pass',
         'Nested map-to-array and nested arrays; complete existing source-path carrier',
         [command(148, '{x: [a, b]} := {x: [1, 2]}'), command(148, '[a, [b, c]] := [1, [2, 3]]'), output(151, 'ok')], 'destructure_test.go', 'TestDestructuringMap/TestDestructuringArray')
material('Tundef', 'agent_validation', 'executed_pass',
         'Missing leaf without default binds UndefinedValue; existing correct undefined test-helper expected value, not proof present undefined plus default ran',
         [command(148, 'ARR{1, tengo.UndefinedValue}')], 'destructure_test.go', 'TestDestructuringArray')
material('Parray', 'temporary_probe', 'executed_pass',
         'Temporary array-default comparison missing50 versus present2, passed after stack fix100',
         [command(94, '[a4, b4 = 50] := [1, 2]'), output(101, '150'), output(101, '12')], '/tmp/d2.tengo')
material('Pparam', 'temporary_probe', 'executed_pass',
         'Map destructured parameter h({}) default99, plus array missing defaults and explicit whole-argument undefined source',
         [command(102, 'h := func({x: v = 99}) { fmt.println(v) }'), command(102, 'h({})'), output(102, '99')], '/tmp/f1.tengo')
material('PparamString', 'temporary_probe', 'executed_pass',
         'String-key destructured map param with present42',
         [command(133, 'h := func({"x": v}) { fmt.println(v) }'), command(133, 'h({"x": 42})'), output(133, '42')], '/tmp/f10.tengo')
material('Pnested', 'temporary_probe', 'executed_pass',
         'Nested array/map default forms with absent outer slot/key provide nested consumer path',
         [command(137, '[a, [b, c] = [10, 20]] := [1]'), command(137, '{x: [d, e] = [3, 4]} := {}'), output(137, '11020')], '/tmp/f14.tengo')
material('PnestedMap', 'temporary_probe', 'executed_pass',
         'Nested map pattern with outer default: absent nested map yields5, present nested map yields7',
         [command(189, '{x: {a} = {a: 5}} := {}'), command(189, '{x: {b} = {b: 6}} := {x: {b: 7}}'), output(189, '7')], '/tmp/f36.tengo')
material('Pshorthand', 'temporary_probe', 'executed_pass',
         'Shorthand map leaf default: missing a50 versus present b1; earlier binding c10 supplies d11',
         [command(139, '{a = 50} := {}'), command(139, '{b = 50} := {b: 1}'), output(139, '50')], '/tmp/f15.tengo')
material('PstringDefault', 'temporary_probe', 'executed_pass',
         'String-key map default50 from empty map',
         [command(142, '{"x": a = 50} := {}'), output(142, '50')], '/tmp/f16.tengo')
material('Pundefined', 'temporary_probe', 'executed_output',
         'Array/map destructuring of whole undefined source prints blank; existing undefined literal and output convention, not present leaf witness',
         [command(176, '[a, b] := undefined'), command(176, '{c} := undefined'), reasoning(177, 'both bind undefined')], '/tmp/f33.tengo')
material('Pcomplex', 'temporary_probe', 'executed_pass',
         'Nested producer and process(map-with-array-param) with defaults at name/tags levels; broad multi-feature input but no present undefined at default leaf',
         [command(175, 'process := func({name: n = "unknown", tags: [t1, t2 = "none"]})'), command(175, 'fmt.println(process({name: "x", tags: ["a"]}))'), output(175, 'x:a:none')], '/tmp/f32.tengo')
material('PerrorDefault', 'temporary_probe', 'executed_fail',
         'Missing array leaf calls noncallable fallback (1)(2), causing intended runtime error; can detect unwanted fallback without adding a counter',
         [command(195, '[a, b = (1)(2)] := [1]'), output(195, 'Runtime Error: not callable: int')], '/tmp/f39.tengo')
material('Darray', 'implementation', 'read_only',
         'Original Array.IndexGet bounds check already has presence information before returning UndefinedValue',
         [output(29, 'idxVal < 0 || idxVal >= len(o.Value)'), output(29, 'res = o.Value[idxVal]')], 'objects.go', 'Array.IndexGet', 'repo_preexisting')
material('Dmap', 'implementation', 'read_only',
         'Original Map.IndexGet receives comma-ok presence information then discards it to UndefinedValue',
         [output(29, 'res, ok = o.Value[strIdx]'), output(29, 'if !ok')], 'objects.go', 'Map.IndexGet', 'repo_preexisting')
material('Ddefault', 'implementation', 'written_unexecuted',
         'New compileDefaultPattern tests extracted UndefinedValue only; source explains exact lost distinction, not an independent oracle',
         [command(63, 'compileDefaultPattern'), output(185, 'jumpDefault := c.emit(node, parser.OpJumpIfUndefined, 0)')], 'destructure.go')
material('RarrayUndefined', 'repo_test', 'repo_unseen',
         'Preexisting VM recursion fixture explicitly creates array with present undefined cell, later overwrites it. Reusable input constructor; original fixture itself no default.',
         [repo('vm_test.go', 'a := [undefined]')], 'vm_test.go', origin='repo_preexisting')
material('Qpresence', 'reasoning', 'reasoning_only',
         'Agent explicitly recognized presence-versus-undefined distinction before implementation',
         [reasoning(28, 'exists'), reasoning(30, 'Since we can\'t distinguish "exists with undefined", we\'ll use undefined-as-missing.')])
material('Qaccept', 'reasoning', 'reasoning_only',
         'Near end explicitly rereads only-missing requirement and declines present-undefined as unlikely hidden test; strong counterevidence to forgetting',
         [reasoning(174, 'This is an acceptable limitation.'), reasoning(227, 'Hidden tests probably won\'t test present-undefined vs missing')])
material('I1', 'issue_or_documentation', 'read_only',
         'Authoritative expected value and laziness: default ONLY if position/key absent; present undefined must stayundefined and fallback not evaluated',
         [dict(channel='issue', path=case['issue'], quote='apply only when a position or key does not exist in the source'), dict(channel='issue', path=case['issue'], quote='evaluate lazily')], 'instruction.md', origin='issue')


def slot(role, alternatives):
    return dict(role=role, alternatives=[[m] for m in alternatives])


recipes = []


def recipe(rid, gap, slots, compatibility, additions, qualification='requires_transfer'):
    recipes.append(dict(id=rid, gap=gap, qualification=qualification, slots=slots,
                        forbidden_pairs=[], compatibility=compatibility, semantic_additions=additions))


recipe('R1', 'G1', [slot('complete existing witness', ['Wmap']), slot('correct task oracle', ['I1'])],
       'Keep exact executed f31 input and operation; assert undefined instead of accepting50. Sideeffect count is optional: bound-value assertion already reveals official root defect.',
       ['Replace JS-derived expected50 with issue-derived expectedundefined.'], 'direct')
recipe('R2', 'G1', [slot('map default base', ['Tmap', 'Pshorthand', 'PstringDefault']), slot('presentundefined input', ['Wmap']), slot('oracle', ['I1'])],
       'Use existing map-default test and substitute historical presentundefined leaf. Rename/shorthand/stringkey all use same compilerpath. Preserve absence-control and correct expectedundefined.',
       ['Transfer exact existing input into existing test; task fixes expected value.'])
recipe('R3', 'G1', [slot('default fallback error', ['PerrorDefault']), slot('map presentundefined shape', ['Wmap']), slot('oracle', ['I1'])],
       'Put known noncallable fallback at existing map default leaf. Presentundefined shouldskipfallback, so any runtimeerror is failure; no new sideeffect-counter oracle needed.',
       ['Transfer historical error-producing fallback into already joint map program.'])
recipe('R4', 'G2', [slot('array default test', ['Tarray', 'Tlazy', 'Parray']), slot('undefined donor', ['Wmap', 'Pundefined', 'RarrayUndefined']), slot('oracle', ['I1'])],
       'Replace present ordinary value in defaulted ARRAY slot with explicitundefined. For mapdonor move only leafliteral, not map operation. Slot mustexist; [] tests missing andwouldpasswrongpatch.',
       ['Transfer existing undefined literal to present defaulted slot; use correctundefined expected value.'])
recipe('R5', 'G2', [slot('arraydefaultbase', ['Tarray', 'Tlazy', 'Parray']), slot('presence source', ['Darray']), slot('undefined expectation helper', ['Tundef']), slot('oracle', ['I1'])],
       'Bounds-check source distinguishes idx<len independently of extractedvalue. Construct [undefined] using alreadyknownlanguageconstant and preserveleafdefault; expect UndefinedValue.',
       ['Materialize input at boundary explicitly identified in original source.'])
recipe('R6', 'G2', [slot('error fallback test', ['PerrorDefault']), slot('undefined donor', ['Wmap', 'Pundefined', 'RarrayUndefined']), slot('oracle', ['I1'])],
       'Make second array slot EXIST as undefined in f39: [1,undefined]. Fallback (1)(2) mustnotrun. This supplies reveal without adding sideeffectcounter or copying verifier.',
       ['Replace absent second slot by explicitundefined; reverse expectederror to successfulundefined binding.'])
recipe('R7', 'G3', [slot('nested consumer', ['Tnested', 'Pnested', 'PnestedMap', 'Pcomplex']), slot('complete leaf defect shape', ['Wmap']), slot('oracle', ['I1'])],
       'Embed existing {key:undefined} and defaulted targetleaf under historical nestedmap/array path. Outercontainersmustexist; donot test missingoutermapfallback instead. Two or three nestedlevels same root loss.',
       ['Transfer leaf-default plus presentundefined into nested consumer; task oracle remains undefined.'])
recipe('R8', 'G3', [slot('nested consumer', ['Tnested', 'Pnested', 'PnestedMap']), slot('default syntax', ['Tmap', 'Pshorthand', 'PstringDefault']), slot('undefined source', ['Pundefined', 'RarrayUndefined']), slot('oracle', ['I1'])],
       'Use preexisting nested carrier, historical defaultsyntax, historical explicitundefined value. Localrename/keysyntax adapted only; no need exact officialouter/inner/v names.',
       ['Combine source path and leaf presence conditions from three existing code units.'])
recipe('R9', 'G4', [slot('parameter consumer', ['Tparam', 'Pparam', 'PparamString', 'Pcomplex']), slot('joint map default shape', ['Wmap']), slot('oracle', ['I1'])],
       'Call a destructured map parameter with a mapwhose defaultedleafEXISTS withundefined. Do not substitute entire argumentundefined or baredefaultparam, which agent intentionallyextendedwithJSsemantics.',
       ['Transfer exactf31 leafcondition across existing parameter-prologue boundary.'])
recipe('R10', 'G4', [slot('existing map default parameter', ['Pparam', 'Pcomplex']), slot('undefined literal', ['Pundefined', 'RarrayUndefined']), slot('undefined test helper', ['Tundef']), slot('oracle', ['I1'])],
       'For Pparam change h({}) to h({x:undefined}), assertundefined, optionally defaultfallbacknoncallable. For Pcomplex use name:undefined withvalid tags to avoidunrelatedmissingpath.',
       ['Move explicitundefined into present mapkey at existing callableinput.'])

by_suffix = lambda suffix: [f['name'] for f in failed if f['name'].endswith(suffix)]
families = [
    dict(id='G1', failed_tests=by_suffix('.TestDestructuring_MapDefaultNotEvaluatedForUndefined'),
         contract='Existing map key with undefined value must remain undefined, not evaluate default.',
         missing_joint_test='Already executed f31: {x:a=50}:={x:undefined}; repair expected value to undefined. Verifier additionally asserts lazy fallback counter0.',
         classification='weak_oracle', verifier_validity='supported', joint_attempt='weak_oracle'),
    dict(id='G2', failed_tests=by_suffix('.TestDestructuring_DefaultNotEvaluatedForUndefined'),
         contract='Existing array slot with undefined value must remain undefined and skip fallback.',
         missing_joint_test='[a=fallback()]:=[undefined]; assert a undefined and optionally no fallback side effect.',
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent'),
    dict(id='G3', failed_tests=by_suffix('.TestDestructuring_DeepNestedDefaultNotForUndefined')+by_suffix('.TestDestructuring_UndefinedPropagatesNotDefault'),
         contract='Nested present undefined leaf is distinct from absent key at every destructuring depth.',
         missing_joint_test='Existing nested map/array path with default at present-undefined leaf; assert undefined survives, fallback unused.',
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent'),
    dict(id='G4', failed_tests=by_suffix('.TestDestructuring_ParamMapDefaultNotEvaluatedForUndefined'),
         contract='Map-pattern parameter follows same only-absent default semantics.',
         missing_joint_test='func({x=fallback()}) called with {x:undefined}; assert returnedundefined, fallback unused.',
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent')
]
review = dict(case_id='S075', reviewer='Codex /root',
              full_read=dict(line_ranges=[[1,25093]], steps=242, unread=[], metadata_read=True),
              evaluation_families=families, materials=materials, recipes=recipes,
              agent_process=dict(joint_attempt='weak_oracle', explanations=[
                  dict(label='explicit_contract_reinterpretation', support='direct',
                       interpretation='28 recognizes existence/undefined distinction;30 choosesundefined-as-missing.174 actuallyrunsmissingjointinputandaccepts50;227 rereads exactissue thenclaimsJSsemantics onlyreasonable andhiddenunlikely. This isdocumentedsemanticdecision, notlongcontextforgetting.',
                       refs=[reasoning(30, 'we\'ll use undefined-as-missing'), reasoning(174, 'This is an acceptable limitation.'), output(174, '50'), reasoning(227, 'Hidden tests probably won\'t test present-undefined vs missing')]),
                  dict(label='abstraction_discards_presence', support='direct',
                       interpretation='29 originalobjectscheckbounds/comma-ok thenreturnUndefinedValue. AgentmistakeslossatIndexGetinterfaceforimpossibilityatobjectmodel, choosesJMPUNDEFvaluecheck. Needsretainpresencebeforeextraction, notnewlanguageoracle.',
                       refs=[output(29, 'res, ok = o.Value[strIdx]'), reasoning(227, 'No distinction possible without changing object model')]),
                  dict(label='broad_feature_matrix_misses_discriminating_value', support='direct',
                       interpretation='148 permanenttests cover missing/presentordinary, nesting,parameter,rest andlazydefault butneverpresentundefinedatdefaultleaf.174temporaryactualbadjointdoesnotcorrectthatmatrix.227checkboxdefaults-lazy deemedcovered.',
                       refs=[command(148, 'func TestDestructuringDefaultsLazy'), command(174, '{x: a = 50} := {x: undefined}'), reasoning(227, 'Defaults lazy: ✓')])
              ], forgetting_assessment='counterevidence'),
              prior_record_corrections=['Missing map combination was actually executed174 and explicitly accepted; not simply AandB testedseparately. Other array/nested/parameter contextsremainunexecuted with presentundefined.',
                                        'Five failedtests are four contextfamilies sharingonepresence-vs-value root defect. Counter-basedoracleisusefulbutnotessential: task-derivedundefinedvaluecheckalreadyrevealsbug.',
                                        'Stock[undefined]fixtureadditionalrepo_unseenconstructor, notagentobservedsource. SeveralpureAgenttests/probesalreadyprovideallneededsyntax/input.'],
              uncertainties=['Alternative sourceassemblies manually checked forcompatibleconstruction; variantsnotgeneratedandexecutedinthisaudit.',
                             'Wholebaredefaultparameterundefinedfeature190isextraJS-likeextension, not evidence sameparameter-mapleafcontract shoulddefault.'])
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2)+'\n')
(directory / 'reviewer_notes.txt').write_text('Read full25093lines/242steps+metadata. All5actualfails map to4contexts of presentundefined-versus-absent. Critical174alreadyjointf31 printed50 accepted asJSsemantics;227explicitreread+hiddenunlikely counterforget. Several alternatives permanenttests+f31,temporarytestpairs,errorfallback,repo[undefined]constructor; no requirement tocopyofficialsideeffectcounter.\n')
(directory / 'reading_status.json').write_text(json.dumps(dict(read_lines=25093,total_lines=25093,steps=242,metadata_read=True),indent=2)+'\n')
