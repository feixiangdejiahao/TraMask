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
                          unit=unit, supports=['G1:clone_shared_capture', 'G2:return_shared_capture'],
                          refs=refs, artifact=artifact, symbol=symbol))


material('Vshare', 'agent_validation', 'executed_pass',
         'Two DISTINCT closures inc/get share mutable local n: in-script inc twice/get2, then Go inc/get3. No Clone and factory itself not Go-called. Temp76/77 consolidated94/110; one semantic unit.',
         [command(76, 'func TestGoCallClosureSharingWithinInstance'), command(94, 'func TestCompiledFunctionCallClosureSharing'), command(110, 'return [inc, get]'), command(110, 'if r.String() != "3"'), output(125, '--- PASS: TestCompiledFunctionCallClosureSharing')],
         'compiled_function_call_test.go', 'TestCompiledFunctionCallClosureSharing')
material('Vclone', 'agent_validation', 'executed_pass',
         'Clone SINGLE mutable local closure, source n1 then call7, clone same n1/different global100 then call102;55 wrong expectations legitimately corrected67',
         [command(55, 'func TestGoCallCloneIsolation'), command(67, 'if ret2.String() != "102"'), command(110, 'func TestCompiledFunctionCallCloneIsolation'), output(125, '--- PASS: TestCompiledFunctionCallCloneIsolation')],
         'compiled_function_call_test.go', 'TestCompiledFunctionCallCloneIsolation')
material('Vclonenested', 'temporary_probe', 'executed_pass',
         'Clone data=[f] where f is a SINGLE local mutator, change clone g100 and Go-call arrayf102; no sibling capture alias to preserve. Temp deleted93.',
         [command(76, 'func TestGoCallCloneNested'), command(76, 'data := [f]'), command(76, 'if r.String() != "102"'), output(85, '--- PASS: TestGoCallCloneNested')], 'zz_repro3_test.go', 'TestGoCallCloneNested')
material('Vcloneglobal', 'temporary_probe', 'executed_pass',
         'After Go-call globalg1→2 Clone then clonef→3/sourceg2 unchanged; only GLOBAL identity',
         [command(87, 'func TestGoCallCloneAfterGoCall'), command(87, 'cl := c.Clone()'), command(87, 'if got := c.Get("g").Int(); got != 2'), output(87, '--- PASS: TestGoCallCloneAfterGoCall')], 'zz_repro4_test.go', 'TestGoCallCloneAfterGoCall')
material('Vreturncomposite', 'agent_validation', 'executed_pass',
         'Go-call mk(x10) returns [inc(y)=x+y,{mul(y)=x*y}], two DISTINCT closures share READ-ONLY captured x, outputs15/50; no mutating write. Earlier76 plainarray and final94/110 nestedmap are retained versions of same case.',
         [command(94, 'func TestCompiledFunctionCallReturnedComposite'), command(110, 'return [inc, { "mul": mul }]'), command(110, 'inc := func(y) { return x + y }'), command(110, 'mul := func(y) { return x * y }'), output(125, '--- PASS: TestCompiledFunctionCallReturnedComposite')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallReturnedComposite')
material('Vreturnclosure', 'agent_validation', 'executed_pass',
         'Go-call make(x10) returns ONE read-only closure y→x+y, inner32→42; supplies callable factory boundary',
         [command(55, 'func TestGoCallReturnedClosure'), command(110, 'func TestCompiledFunctionCallReturnedClosure'), command(110, 'return func(y) { return x + y }'), output(125, '--- PASS: TestCompiledFunctionCallReturnedClosure')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallReturnedClosure')
material('Vreturnmap', 'temporary_probe', 'executed_pass',
         'Distinct Go factory mk(x40) returns MAP containing ONE read-only closure and scalarx, inner2→42',
         [command(86, 'func TestGoCallReturnMapWithClosures'), command(86, 'return { "inc": inc, "x": x }'), output(86, '--- PASS: TestGoCallReturnMapWithClosures')], 'zz_repro4_test.go', 'TestGoCallReturnMapWithClosures')
material('Vsetalias', 'agent_validation', 'executed_pass',
         'Set nested array/map contains SAME function object twice over localn; original152fail81 weakened82/85 to151, then101memo fixes SAME-FUNCTION identity and104 RESTORES correct152. Final same-function case does not test DISTINCT sibling shared-cell identity.',
         [command(76, 'return [inc, { "inc": inc }]'), output(81, 'map inc got 151'), command(85, '84s/"152"/"151"/'), output(103, 'map closure returned 152'), command(104, 'if r2.String() != "152"'), output(125, '--- PASS: TestCompiledFunctionCallNestedTransferIsolation')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallNestedTransferIsolation')
material('Vsetone', 'agent_validation', 'executed_pass',
         'Set ONE mutated local closure into same-layout instance, g100/n2→103 vs source13; valid snapshot oracle corrected67',
         [command(67, 'func TestGoCallTransferIsolation'), command(110, 'func TestCompiledFunctionCallTransferIsolation'), command(110, 'if r2.String() != "103"'), output(125, '--- PASS: TestCompiledFunctionCallTransferIsolation')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallTransferIsolation')
material('Vnestedcall', 'agent_validation', 'executed_pass',
         'Outer closure captures inner inc, both ultimately localn, Set transfer; source leak98(2/3) correctly fixed101(2/2), but outer itself does not independently read/write same n',
         [command(97, 'outer := func() { return inc() }'), output(98, 'f1: 3'), output(102, 'f1: 2'), command(110, 'func TestCompiledFunctionCallNestedClosureIsolation'), output(125, '--- PASS: TestCompiledFunctionCallNestedClosureIsolation')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallNestedClosureIsolation')
material('Vadd', 'agent_validation', 'executed_pass',
         'Add SINGLE local closure to different script; executesf in-script then Go again, n1→2→3; no globals after107 removesglobaldependency',
         [command(110, 'func TestCompiledFunctionCallAddTransfer'), command(111, 'if ret.String() != "3"'), output(125, '--- PASS: TestCompiledFunctionCallAddTransfer')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallAddTransfer')
material('Vmodule', 'agent_validation', 'executed_pass',
         'Source module exports one add closure capturing modulelocalx1, Go20+21+1→42; alternate local-sharing construction context',
         [command(110, 'func TestCompiledFunctionCallSourceModuleExport'), command(110, 'x := 1'), command(110, 'export { "add": add }'), output(125, '--- PASS: TestCompiledFunctionCallSourceModuleExport')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallSourceModuleExport')
material('Vglobal', 'agent_validation', 'executed_pass',
         'Go-call bump twice globalg5→15→25; no shared LOCAL relationship',
         [command(110, 'func TestCompiledFunctionCallGlobalMutation'), command(110, 'bump := func() { g += 10; return g }'), output(125, '--- PASS: TestCompiledFunctionCallGlobalMutation')], 'compiled_function_call_test.go', 'TestCompiledFunctionCallGlobalMutation')
material('P32', 'temporary_probe', 'executed_output',
         'Deleted zz_repro: ONE read-only closure captures y10+globalg5; GoCallinitialnil32 then15afterfix54',
         [command(31, 'y := 10'), output(32, 'call ret: <nil> err: <nil>'), output(54, 'call ret: 15 err: <nil>')], 'zz_repro_test.go', 'TestClosureGlobalRepro')
material('Rshared', 'repo_test', 'repo_unseen',
         'Original vm_test factory returns b/c/d sharing same local a1; writes+3/+2 then reader6. Stock suite executes it, exact source never printed in retained history.',
         [repo('vm_test.go', 'b: func() { a += 3 },'), repo('vm_test.go', 'c: func() { a += 2 },'), repo('vm_test.go', 'out = m.d()\n`, nil, 6)')], 'vm_test.go', 'TestAssignment:factory-map-shared-local', 'repo_preexisting')
material('Rindirect', 'repo_test', 'repo_unseen',
         'Another original TestAssignment: returned outerclosure independently writes a and calls add1/add2 sharing a; cumulative20. Different valid behavior from literal verifiermap.',
         [repo('vm_test.go', 'add1 := func() { a += 1 }'), repo('vm_test.go', 'return func() { a += 4; add1(); add2(); a += 5; return a }'), repo('vm_test.go', '`, nil, 20)')], 'vm_test.go', 'TestAssignment:shared-local-through-helpers', 'repo_preexisting')
material('Rclone', 'repo_test', 'read_only',
         'Original TestCompiled_Clone source actually read72: snapshot count1000/dataa1, cloneRun changes1001/data2, sourceunchanged',
         [output(72, 'func TestCompiled_Clone(t *testing.T)'), output(72, 'clone := compiled.Clone()'), output(72, 'require.Equal(t, 1001, clone.Get("count").Int())')], 'script_test.go', 'TestCompiled_Clone', 'repo_preexisting')
material('Dvm', 'implementation', 'read_only',
         'Original VM OpClosure preserves shared ObjectPtr; compiler uses FreePtr/LocalPtr; re-read39',
         [output(39, 'free[i] = freeVar'), output(26, 'c.emit(node, parser.OpGetFreePtr, s.Index)')], 'vm.go/compiler.go', 'OpClosure', 'repo_preexisting')
material('Dcopy', 'implementation', 'read_only',
         'Original CompiledFunction.Copy explicitly must not copy free-variable pointer elements; read6/48',
         [output(48, 'DO NOT Copy() of elements; these are variable pointers')], 'objects.go', 'CompiledFunction.Copy', 'repo_preexisting')
material('D101', 'implementation', 'written_unexecuted',
         'Final recursive binding memoizes function/container object but not ObjectPtrcell; each distinct function receives freshFreecell',
         [command(101, 'seen[o] = bound'), command(101, 'val := bindObjectRec(*p.Value, ctx, seen)'), command(101, 'free[i] = &ObjectPtr{Value: &val}')], 'objects.go', 'bindContextRec')
material('Q38', 'reasoning', 'reasoning_only',
         'Explicit two distinct closure samecapture example: snapshotting at creation breaks inc/getsharing; appliesrequirement only creation nottransferboundary',
         [reasoning(38, 'the two closures would not share x'), reasoning(38, 'That would break in-script semantics!')])
material('Q104', 'reasoning', 'reasoning_only',
         'After initialweakening, late104restores rule: isolationbetweeninstances andsharingwithindestination bothneeded',
         [reasoning(104, 'The source had them sharing n; after transfer they should still share'), reasoning(104, 'The important isolation is between c1 and c2, not within c2.')])
material('Q101', 'reasoning', 'reasoning_only',
         'Late explicitly identifies sharedfree identity acrossglobals but chooses nottested assumption; pertop-levelmapsacceptabledecision',
         [reasoning(101, 'For correctness, Clone should preserve sharing'), reasoning(101, 'Hidden tests probably don\'t test this'), reasoning(101, 'For composite values, sharing within the same top-level value is preserved')])
material('Q121', 'reasoning', 'reasoning_only',
         'Immediately beforecommit revisits Clonealiasloss andaccepts despiteacknowledgedbehaviorchange',
         [reasoning(121, 'they become independent, which IS a behavior change'), reasoning(121, 'The task prioritizes isolation. Fine.')])
material('I1', 'issue_or_documentation', 'read_only',
         'Same closurecaptures/in-script semantics plus recursivelyisolatedtransferredcomposites; copyingmust preserve internalsharingwhileisolateinstances',
         [dict(channel='issue', path=case['issue'], quote='executes with the same globals, imports, closure captures'), dict(channel='issue', path=case['issue'], quote='Returned closures and composite values must stay callable'), dict(channel='issue', path=case['issue'], quote='Apply the same isolation recursively to every callable reachable inside transferred arrays or maps')], 'instruction.md', origin='issue')


def slot(role, alternatives):
    return dict(role=role, alternatives=[[mid] for mid in alternatives])


recipes = []


def recipe(rid, gap, slots, compatibility, additions):
    recipes.append(dict(id=rid, gap=gap, qualification='requires_transfer', slots=slots,
                        forbidden_pairs=[], compatibility=compatibility, semantic_additions=additions))


recipe('R1', 'G1', [slot('Clone boundary', ['Vclone', 'Vclonenested', 'Vcloneglobal', 'Rclone']), slot('complete distinctsiblings sharedlocal program andoracle', ['Vshare', 'Rshared']), slot('contract', ['I1'])],
       'Move unchanged inc/get or b/c/d factoryprogram intoClonebasetest. Clone beforemutator→siblingread, preserve cumulative3or6andchecksourceunchanged. Bothsiblingsmust be selectedfromsameclonegraph; no separate Set calls.',
       ['Connect existing Clone and existing complete shared-local program; adapt clonedcontainer retrieval and seedstage.'])
recipe('R2', 'G1', [slot('nested local composite', ['Vreturncomposite']), slot('mutable sharing operations', ['Vshare', 'Rshared']), slot('Clone boundary', ['Vclone', 'Vclonenested', 'Rclone']), slot('contract', ['I1'])],
       'Keep nestedarray/maplayout butreplacepure inc/mulbody with existing samecellwriter/reader. Execute factoryin-script,Clone,thenwriter/readerthroughclone. Keepingreadonlysiblingswouldnotrevealcellidentityloss.',
       ['Transfer existing mutation/observationinto returnedcomposite, thenClone.'])
recipe('R3', 'G1', [slot('samefunction Setalias test', ['Vsetalias']), slot('distinctsiblings provider', ['Vshare', 'Rshared']), slot('Clone boundary', ['Vclone', 'Vclonenested', 'Rclone']), slot('contract', ['I1'])],
       'Replace twooccurrencesofsameinc with twoDISTINCTclosures sharingn, preservejointcumulativeexpectation, andClone insteadSet. Vsetalias alone passesbecausefunctionmemo isenoughforidenticalfn, notdifferentfnssamecell.',
       ['Move sharedcell test across knowncopyboundary and differentiate siblingfunctionobjects.'])
recipe('R4', 'G1', [slot('indirectsharedcell program', ['Rindirect']), slot('Clone boundary', ['Vclone', 'Vclonenested', 'Rclone']), slot('contract', ['I1'])],
       'Keep outerclosure and add1/add2 in samefactory and a5. Store factoryresult,Clone beforefinalCall; correctresult20musthold. Noofficialboxneeded.',
       ['RetaincrossclosurealiasgraphandinsertClonebefore finalGoCall.'])
recipe('R5', 'G1', [slot('existing per-instance test', ['Vclone', 'Vclonenested']), slot('knownsharedcell rule', ['Dvm', 'Dcopy']), slot('explicitlateobligation', ['Q104', 'Q101', 'Q121']), slot('existing distinctsibling behavior', ['Vshare']), slot('contract', ['I1'])],
       'Explicitsharingobligationguides moving bothVshareclosures into one clonedgraph. Source-onlyrule isguidance, not countedalreadyexecutedjoint.',
       ['Materialize statedsharingrelation using existing fullwriter/readerprogram.'])
recipe('R6', 'G2', [slot('Go factory returnboundary', ['Vreturncomposite', 'Vreturnclosure', 'Vreturnmap']), slot('distinctsamecell writer/readerprogram', ['Vshare', 'Rshared']), slot('contract', ['I1'])],
       'Go-call factoryinsteadin-script, get bothclosuresfromsame returnedvalue, writerthenreader. ForVshare n0 writer2timesreader2 oronewriterreader1; forRshared preserve+3/+2→6. NoClone required. Factoryreturnbind independentlycopiesFreecellofdistinctfns.',
       ['Transfer existing complete mutablepair into Go-callreturnedcontainer.'])
recipe('R7', 'G2', [slot('sameclosureduplicatednestedcontainer', ['Vsetalias']), slot('distinctpairprogram', ['Vshare', 'Rshared']), slot('factoryGoCall', ['Vreturncomposite', 'Vreturnclosure', 'Vreturnmap']), slot('contract', ['I1'])],
       'TakeVsetaliasnestedcontainer buttwo distinctfunctions overn, generatedbyfactoryGoCall notSet. Original152oracleprovidescumulativeoperationpattern; withinc/get adapttoexactexistingVshareexpectations.',
       ['PreservecellsharingratherthansamefunctionidentityacrossGoReturn.'])
recipe('R8', 'G2', [slot('indirectsharedcell behavior', ['Rindirect']), slot('Go factory return boundary', ['Vreturnclosure', 'Vreturnmap', 'Vreturncomposite']), slot('contract', ['I1'])],
       'ReturnRindirect outerclosure byGoCall,thenCallit. Correct20depends onoutercaptured a andadd1/add2capturingSAMEa. CurrentrecursivebindingclonesinnerfunctionsbutallocatesdifferentFreecells. Originalprogramhasdirectexisting20oracle.',
       ['Move existingfactoryexecution to Go boundary thenpreservefinalCall.'])
recipe('R9', 'G2', [slot('nested captured helper', ['Vnestedcall']), slot('samecellwriteandreadprogram', ['Vshare', 'Rindirect']), slot('Go factory returnboundary', ['Vreturnclosure', 'Vreturnmap']), slot('contract', ['I1'])],
       'Existingoutercallsincbutdoesnotitselftouchsamecell; addexistingdirectread/write ofn toouteralongsideinc thenreturnouterthroughGoCall. Rindirect iscompleteexistingvariant, Vshare suppliesdirectread andmutatororacle. Merelynestedhelperwithoutsharedsecondroutepasses.',
       ['Connectindependentcaptureroutes toonecellbeforeGoReturn.'])
recipe('R10', 'G2', [slot('nestedreadonlyreturnedprogram', ['Vreturncomposite']), slot('originalcapturealiasingsemantic', ['Dvm', 'Dcopy']), slot('explicitsharingobligation', ['Q38', 'Q104']), slot('existingmutablepair', ['Vshare']), slot('contract', ['I1'])],
       'Use originalVM sharedcellrule andlate104sharingcomment totransferVsharewriter/readerintoexistingGoReturntest. No newlyinventedoracle beyond copiedexistingchecks.',
       ['Changeexistingread-onlypair intohistoricalmutablewriter/readerpairatreturnboundary.'])

families = [
    dict(id='G1', failed_tests=[failed[0]['name']], contract='Clone must isolate source while preserving aliasing between distinct closures over the same mutable local inside the cloned graph.',
         missing_joint_test='Create writer/read siblings capturing one local, store both in one graph, Clone, call writer and siblingreader in clone, assert mutation visible inside clone and source unchanged.',
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent',
         required_components=['distinct closure objects', 'same mutable captured cell', 'same copied container graph', 'Compiled.Clone', 'write followed by sibling read'],
         patch_explanation='bindContextRec memoizes closure object identity, not shared ObjectPtr identity; every distinct function receives fresh captured cell. Clone also binds perglobal after independent Copy. Soleclosure and samefunctiontwicetests pass.'),
    dict(id='G2', failed_tests=[failed[1]['name']], contract='A composite returned from a Go-called factory must preserve in-script shared-capture behavior among its distinct callable members.',
         missing_joint_test='Go-call factory returning two or more distinct closures over one mutable local; mutate through one, then another, and observe through sibling. Expected cumulative9 must remain9, not8.',
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent',
         required_components=['factory invoked from Go', 'returned composite contains distinct siblings', 'same mutable local', 'cross-sibling write/read sequence'],
         patch_explanation='Call binds returned graph using same bindContextRec. Read-only inc/mul pair is jointbutnondiscriminating: separate copiedx valuesreturn15/50equally. Shared-writer/reader test bypasses factoryGoCall boundary entirely.')
]
review = dict(case_id='S074', reviewer='Codex /root',
              full_read=dict(line_ranges=[[1,19258]], steps=126, unread=[], metadata_read=True,
                             note='All retained text read sequentially. Originalharness elidedoutput retainedasrecord, notinferredasread. OwnCASstocksharedlocal programs inspectedafterfullread andmarkedrepo_unseen.'),
              evaluation_families=families, materials=materials, recipes=recipes,
              agent_process=dict(joint_attempt='absent', explanations=[
                  dict(label='relation_not_transferred_across_boundary', support='direct',
                       interpretation='76/94/110 containcomplete inc/getsharingtest,Clone-singleclosuretest andGoReturn-readonlysiblings. Missingrelation isdistinctsiblingmutablecellatClone/GoReturnboundary. Samefile alreadycontainsallconstituents.',
                       refs=[command(110, 'func TestCompiledFunctionCallClosureSharing'), command(110, 'func TestCompiledFunctionCallCloneIsolation'), command(110, 'func TestCompiledFunctionCallReturnedComposite')]),
                  dict(label='wrong_oracle_revised_then_partly_recovered', support='direct',
                       interpretation='81correct152expectationFAIL151;82explicitlysaysindependentposttransfersnapshotscorrect,85weakens151.101recursivefunctionmemo fixesidenticalfunctionaliasing,103new152FAILthen104restorescorrect152. Finalpatchthereforedoesnotretainthissamefunctionbug, butdistinctfunctionsameFreecellstilluntested. Do not counttheearlierweakenedcaseasfinalwitness.',
                       refs=[reasoning(82, 'separate snapshots are correct'), command(85, '84s/"152"/"151"/'), reasoning(104, 'preserves sharing within the transferred composite value')]),
                  dict(label='isolation_prioritized_over_internal_aliasing', support='direct',
                       interpretation='38explicitlyknowsdistinctclosuresmustsharecapture.101and121discussClonecrossglobalidentitylossbutacceptbecausetaskprioritizesisolationandhiddenlikelynottest. Activeboundarychoice, notinferenceofforgettingfromlongcontext.',
                       refs=[reasoning(38, 'the two closures would not share x'), reasoning(101, 'For correctness, Clone should preserve sharing'), reasoning(121, 'The task prioritizes isolation. Fine.')]),
                  dict(label='green_checklist_as_completion_signal', support='direct',
                       interpretation='125latecompletionchecks7requirementsand20namedgreenvalidationtests,voluntarily126submitsafterrace/fullsuite. Peak191397tokensdoesnotitselfidentifyforgetting;explicitnearendacknowledgementcounterevidence.',
                       refs=[reasoning(125, 'Cloned compiled instances and callable values assigned into another instance keep isolated state'), output(125, '--- PASS: TestCompiledFunctionCallClosureSharing'), reasoning(126, 'The implementation is complete and committed')])
              ], forgetting_assessment='counterevidence'),
              prior_record_corrections=[
                  'KnownT13; twoactualfailedtests giveTWOdistinct copyboundaries. HistoricalsharedpairVshare+CloneandVshare+GoReturnarepureAgentroutes; stockTestAssignmentisnotunique.',
                  'Oldstockexactsnippetisrepo_unseen, whileoriginalCloneexactsourceisactuallyread72. Fullsuiterun isnot equivalenttosourcevisibility.',
                  'Sameclosuretwicepreservedbyfunctionmemo after101/104; distinctclosureswithsameFreecell stilllost. Theseidentityrelationsmustnotbemerged.',
                  '82/85initialwrongoracleweakeningwaspartlyundone104. Legitimateseedcorrections67,111arenotweakenedwitnesses. Crossscriptglobalindexissue107isaseparatedesignlimitation, notthetwoactualheldoutfailures.'
              ],
              uncertainties=['Alternativeassembliesaremanualconstructionanalyses,notsynthesizedandexecutedinthisaudit. Originalharnessomittedmiddleoutputs remainunavailable,including108corruptedtestfiledump;reconstructedfinalsourceisexplicit110.'])
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(directory / 'reviewer_notes.txt').write_text('Full19258lines/126steps+metadata read. Two supportedfamilies: Clone distinctsiblingssamecapturedcell; GoCallfactoryreturnedcomposite distinctsiblingssamecell. CompleteAgentVshare inc/get3 andCloneoneclosure/GoReturnreadonlypairprovidepureAgenttwo-wayroutes. SamefunctionduplicatedSet151 initiallyaccepted82/85, restored152after101memo104; donotmisclassifyasretainedweakenedwitness. Late121explicitisolationprioritycounterforget. Stocksharedmapandindirecthelper20areadditionalrepo_unseenalternatives, originalCloneactuallyread72.\n')
