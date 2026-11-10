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


def output(step, quote, call=0):
    return dict(step=step, call=call, channel='output', quote=quote)


def reasoning(step, quote):
    return dict(step=step, channel='reasoning', quote=quote)


def repo(name, quote):
    sha = entries[name]['sha256']
    return dict(channel='repo', path=str(cas / sha[:2] / sha), quote=quote)


materials = []


def material(mid, kind, availability, unit, refs, artifact='', symbol='', origin='agent_authored'):
    materials.append(dict(id=mid, kind=kind, origin=origin, availability=availability,
                          unit=unit, supports=['G1:shared_capture_clone'], refs=refs, artifact=artifact, symbol=symbol))


material('B43', 'agent_validation', 'executed_pass', 'Clone composite of two distinct mutators sharing GLOBAL n; initial seed expectations wrong43, corrected52 to11/13, clone global13 and source10',
         [command(43, 'func TestCompiled_Clone_CompositeRecursiveIsolation'), command(43, 'f1 := func() { n += 1; return n }'), command(43, 'f2 := func() { n += 2; return n }'), command(52, 'require.Equal(t, int64(13), r2.(*tengo.Int).Value)'), output(52, '--- PASS: TestCompiled_Clone_CompositeRecursiveIsolation')], 'call_test.go', 'TestCompiled_Clone_CompositeRecursiveIsolation')
material('Bclosure', 'agent_validation', 'executed_pass', 'Clone one closure capturing local n, repeated Go calls preserve own snapshot and source isolation; snapshot seed expectation corrected52',
         [command(43, 'func TestCompiled_Clone_ClosureIsolation'), command(43, 'return func() { n += 1; return n }'), command(52, '// source captured n is already 1; clone snapshots it at transfer time'), output(52, '--- PASS: TestCompiled_Clone_ClosureIsolation')], 'call_test.go', 'TestCompiled_Clone_ClosureIsolation')
material('Bglobal', 'agent_validation', 'executed_pass', 'Clone one global mutator; source advances2 before cloning, corrected snapshot3/4/5, source staysindependent',
         [command(43, 'func TestCompiled_Clone_Isolation'), command(52, '// clone starts from the copied global value (x = 2)'), output(52, '--- PASS: TestCompiled_Clone_Isolation')], 'call_test.go', 'TestCompiled_Clone_Isolation')
material('Tset', 'agent_validation', 'executed_pass', 'Set transfers composite two mutators sharing GLOBAL n, correct cumulative1/11; source isolation checked with101 after correction53',
         [command(43, 'func TestCompiled_Set_TransferredCompositeRecursiveIsolation'), command(43, 'f2 := func() { n += 10; return n }'), command(43, 'require.Equal(t, int64(11), r2.(*tengo.Int).Value)'), output(53, '--- PASS: TestCompiled_Set_TransferredCompositeRecursiveIsolation')], 'call_test.go', 'TestCompiled_Set_TransferredCompositeRecursiveIsolation')
material('Lstate', 'agent_validation', 'executed_pass', 'Counter factory creates one closure over shared local n0, Go calls1/2/3',
         [command(43, 'func TestCompiledFunction_Call_ClosureState'), command(43, 'n := 0'), command(43, 'require.Equal(t, int64(3), r3.(*tengo.Int).Value)'), output(52, '--- PASS: TestCompiledFunction_Call_ClosureState')], 'call_test.go', 'TestCompiledFunction_Call_ClosureState')
material('Ltransfer', 'agent_validation', 'executed_pass', 'Transferred single mutable-local closure starts source n2, destination snapshot3/4 and source3',
         [command(43, 'func TestCompiled_Set_TransferredClosureSnapshot'), command(43, '// destination sees captures as of transfer time (n=2)'), output(53, '--- PASS: TestCompiled_Set_TransferredClosureSnapshot')], 'call_test.go', 'TestCompiled_Set_TransferredClosureSnapshot')
material('Lreturned', 'agent_validation', 'executed_pass', 'Factory local m=n returns mutator; Go calls11/12 after correction61; supplies alternate local name',
         [command(60, 'func TestCompiledFunction_Call_ReturnedClosureState'), command(60, 'm := n'), command(61, 'require.Equal(t, int64(11), res.(*tengo.Int).Value)'), output(61, '--- PASS: TestCompiledFunction_Call_ReturnedClosureState')], 'call_test.go', 'TestCompiledFunction_Call_ReturnedClosureState')
material('Lgo', 'agent_validation', 'executed_pass', 'Go-invoked make(n) returns mutable closure over its PARAMETER n; mutated11 before transfer then both12',
         [command(64, 'func TestCompiled_Set_GoSideReturnedClosureTransfer'), command(64, 'make := func(n) { return func() { n += 1; return n } }'), output(64, '--- PASS: TestCompiled_Set_GoSideReturnedClosureTransfer')], 'call_test.go', 'TestCompiled_Set_GoSideReturnedClosureTransfer')
material('Larray', 'agent_validation', 'executed_pass', 'Go factory returns ARRAY containing closure capturing parameter n7; innerCall35→42',
         [command(64, 'func TestCompiledFunction_Call_ReturnsArrayWithClosure'), command(64, 'return [func(x) { return x + n }]'), output(64, '--- PASS: TestCompiledFunction_Call_ReturnsArrayWithClosure')], 'call_test.go', 'TestCompiledFunction_Call_ReturnsArrayWithClosure')
material('M73', 'agent_validation', 'executed_pass', 'Source module returns MAP with two different read-only siblings add/mul sharing local base3; no Clone and no mutation',
         [command(73, 'func TestCompiledFunction_Call_SourceModuleMapExport'), command(73, 'm := {"add": func(x) { return x + base }, "mul": func(x) { return x * base }}'), output(73, '--- PASS: TestCompiledFunction_Call_SourceModuleMapExport')], 'call_test.go', 'TestCompiledFunction_Call_SourceModuleMapExport')
material('N60', 'agent_validation', 'executed_pass', 'Set nested map→map→array→function with global n; independent state assertions reordered61; can carry sharedlocalpair',
         [command(60, 'func TestCompiled_Set_TransferredNestedMap'), command(60, 'm := {"inner": {"arr": [f]}}'), output(61, '--- PASS: TestCompiled_Set_TransferredNestedMap')], 'call_test.go', 'TestCompiled_Set_TransferredNestedMap')
material('P23', 'temporary_probe', 'executed_output', 'Original heredoc probe creates local-counter closure, Go calls initiallynil then36 afterimplementation1/2; reused92',
         [command(23, 'n := 0; return func() { n += 1; return n }'), output(36, 'closure calls: 1 2')], '/tmp/repro/main.go')
material('P49', 'temporary_probe', 'executed_output', 'Temporary in-package clone debug confirms original and clone separate fn/globals, sourcex1 clonex2; removed52',
         [command(49, 'func TestZZDebug'), output(49, 'sameFn=false'), output(49, 'origx=1 clonex=2')], 'zz_debug_test.go')
material('Rshared', 'repo_test', 'repo_unseen', 'Original TestAssignment exact factory returns map b/c/d with two local a mutators and reader; expected6 after+3,+2. Executed stock suite, exact source not read in history',
         [repo('vm_test.go', 'b: func() { a += 3 },'), repo('vm_test.go', 'c: func() { a += 2 },'), repo('vm_test.go', 'out = m.d()\n`, nil, 6)')], 'vm_test.go', 'TestAssignment:factory-map-shared-local', 'repo_preexisting')
material('Rindirect', 'repo_test', 'repo_unseen', 'Distinct original TestAssignment returned closure captures two helper closures add1/add2 and same local a; expected20 after sequentialeffects. Clone outerclosure duplicates sharedcell differently across Free slots',
         [repo('vm_test.go', 'add1 := func() { a += 1 }'), repo('vm_test.go', 'return func() { a += 4; add1(); add2(); a += 5; return a }'), repo('vm_test.go', '`, nil, 20)')], 'vm_test.go', 'TestAssignment:shared-local-through-helper-closures', 'repo_preexisting')
material('Roldclone', 'repo_test', 'repo_unseen', 'Original TestCompiled_Clone compiles script with host count/data, clones and RunContext, asserts original unchanged and clone updated',
         [repo('script_test.go', 'func TestCompiled_Clone(t *testing.T)'), repo('script_test.go', 'clone := compiled.Clone()'), repo('script_test.go', 'require.Equal(t, 1001, clone.Get("count").Int())')], 'script_test.go', 'TestCompiled_Clone', 'repo_preexisting')
material('D7', 'implementation', 'read_only', 'Original VM sibling captures reuse existing ObjectPtr; SetLocal/SetFree mutate pointee, explicitly documenting same-local multiple free references',
         [output(7, '// itself. this is needed because there can be free variables',1), output(7, 'free[i] = freeVar',1), output(7, '*v.curFrame.freeVars[freeIndex].Value = v.stack[v.sp-1]',1)], 'vm.go', 'OpClosure/OpSetFree', 'repo_preexisting')
material('D5', 'implementation', 'read_only', 'Original closure Copy deliberately preserves Free pointer elements; supplies aliasing invariant independently of one example',
         [output(5, 'DO NOT Copy() of elements; these are variable pointers')], 'objects.go', 'CompiledFunction.Copy', 'repo_preexisting')
material('D27', 'implementation', 'written_unexecuted', 'Authored graphcloner memoizes functions/containers, yet eachfree slot fresh ObjectPtr and scalarCopy, so sharedcell identity lost',
         [command(27, 'c.clones[o] = cl'), command(27, 'cl.Free[i] = &ObjectPtr{Value: &v}'), command(27, 'v = c.clone(*ptr.Value)')], 'call.go', 'objectCloner.clone')
material('Q20', 'reasoning', 'reasoning_only', 'Early explicitly states two closures share samepointer and cloning must preserve internalsharing; distinguishes cycles but eventual implementation fails pointermemo',
         [reasoning(20, 'if two Free entries share the same ObjectPtr'), reasoning(20, 'the copy should probably preserve that sharing')])
material('Q21', 'reasoning', 'reasoning_only', 'Plans copyForInstance perglobal, assumes recursion handling enough',
         [reasoning(21, "We'll replace with our clone helper to handle cycles and rebind.")])
material('Q64', 'reasoning', 'reasoning_only', 'Late completeclaim isolates closures/composites but tests still singlelocalclosure or global siblings',
         [reasoning(64, 'Cloned compiled instances and callable values assigned into another compiled instance must keep isolated state'), reasoning(64, 'recursive clone')])
material('I1', 'issue_or_documentation', 'read_only', 'Original same closure captures/in-script semantics plus recursive transferisolation; distinctcellswithinclonewouldchangeoriginalbehavior',
         [dict(channel='issue',path=case['issue'],quote='executes with the same globals, imports, closure captures'), dict(channel='issue',path=case['issue'],quote='Apply the same isolation recursively to every callable reachable inside transferred arrays or maps')], 'instruction.md', origin='issue')


def slot(role, alternatives):
    return dict(role=role, alternatives=[[mid] for mid in alternatives])


recipes = []


def recipe(rid, slots, compatibility, additions, qualification='requires_transfer'):
    recipes.append(dict(id=rid,gap='G1',qualification=qualification,slots=slots,forbidden_pairs=[],compatibility=compatibility,semantic_additions=additions))


recipe('R1',[slot('已有Clone基测试',['B43','Bclosure','Bglobal','Roldclone']),slot('已有完整局部共享程序及oracle',['Rshared']),slot('合同',['I1'])],
       '将stockfactory源码保留于script，调用make得到map；先Clone，再从两实例取b/c/d并调用。保留stock正确累计6；原A不变；或把已有B43的两mutator放factory局部n10并继续11/13。stock source未在轨迹读出，单列repo来源。', ['在已有局部共享程序加入已存在Clone与GoCall边界；适配取map或array和独立globals尾断言。'])
recipe('R2',[slot('两个共享GLOBAL的已测试mutator',['B43','Tset']),slot('局部capture构造与快照来源',['Bclosure','Lstate','Ltransfer','Lreturned','Lgo','P23']),slot('Clone边界',['B43','Bclosure']),slot('合同',['I1'])],
       '将同一对不同mutator一起移动到同一factory，seed10并返回原array；不能各自单独factory。B43累计11/13保留，Tset的+1/+10用1/11或seed10→11/21。若保留outerglobal，尾断言改为未变，因为现在变的是capturedlocal。仅用Agent编写材料即可，无需stock唯一片段。', ['把global共享存储迁移到一个factory-local；维持共享身份和顺序；添加/保留Clone。'])
recipe('R3',[slot('原局部closure Clone',['Bclosure']),slot('已有双mutator及累计oracle',['B43','Tset']),slot('局部factory来源',['Lstate','Ltransfer','Lreturned','Lgo']),slot('合同',['I1'])],
       '扩展单closurefactory为含原closure和第二个mutator的array/map，两个函数必须capture同一n/m。保留源clone独立性，再比较同clone中第二函数累计读取的状态；不能只比较不同实例各自返回2。', ['把已存在第二操作接到同一capturedcell；保留Clone再取两函数。'])
recipe('R4',[slot('module双sibling局部输入',['M73']),slot('已有mutator',['B43','Tset','Lstate']),slot('Clone边界',['B43','Bclosure','Bglobal']),slot('原共享语义',['D7','D5','Rshared']),slot('合同',['I1'])],
       'modulebase已是共享local的两个不同closure，改其中一个按历史mutator方式更新base，再Clone持有modulemap的Compiled，GoCall两sibling。add/mul原为只读，光Clone不揭错；必须用已有写操作。immutablemap取值在Clone后按实际Map类型适配。', ['给一个现成sibling迁移已有写操作；Clone后检查另一个可见性。'])
recipe('R5',[slot('原嵌套Map或Array承载程序',['N60','Larray']),slot('双mutator',['B43','Tset']),slot('同一factorylocal',['Bclosure','Lstate','Lreturned','Lgo']),slot('Clone边界',['B43','Bclosure']),slot('合同',['I1'])],
       '保留nestedmap→array或factoryarray路径，把两个mutator放同一factory同一local中并接入Clone测试。深层容器字面路径不是必须与官方box相同；关键是两条不同函数的Free同一个cell，随后Clone并执行两条。', ['连接sharedcapture和Clone，保留嵌套容器访问骨架；按现有累计值建立oracle。'])
recipe('R6',[slot('另一个完整局部共享行为',['Rindirect']),slot('Clone与Go调用',['Bclosure','Bglobal','Roldclone']),slot('合同',['I1'])],
       '原返回closure同时捕获a、add1、add2，helper也捕获a。用其返回closure作全局再Clone，GoCall应仍等于20；无需引入官方next/readmap。该替代程序通过跨closure相同Free关系击中同cloner错误。', ['将原即时()()改成存储factory返回closure，在最后调用前Clone；沿同一共享cell保持20oracle。'])
recipe('R7',[slot('同一cell的源码约定',['D7','D5']),slot('明确共享身份要求',['Q20']),slot('现成双操作Clone测试',['B43']),slot('局部构造',['Bclosure','Lstate','Lreturned']),slot('合同',['I1'])],
       '由OpClosure直接reuseObjectPtr的语义把两个已有mutator重定位到相同local，保留B43先后累计oracle。源码/推理关系可以指导构造，但没有当作已实际运行完整joint。', ['实体化已陈述的sharedcell不变量，连接Clone边界。'])

family=dict(id='G1',failed_tests=[failed[0]['name']],contract='A cloned object graph must isolate source state while preserving aliases between sibling closures sharing one captured local inside the clone; Go calls retain in-script capture semantics.',
            missing_joint_test='Create two distinct closures over the SAME mutable local (writer+reader or two writers), put both in one container, Clone compiled instance, execute writer then sibling in the clone, assert cumulative sharedstate and source unaffected.',classification='untested_interaction',verifier_validity='supported',joint_attempt='absent',
            required_components=['two distinct sibling closures','same captured LOCAL cell, not global','both retained in same copied graph','Compiled.Clone','sequential write then sibling observation','correct withinclone sharing plus crossinstance isolation oracle'],
            patch_explanation='Function/container identity memoization does not memoize ObjectPtr captured-cell identity; each function Free slot creates fresh ObjectPtr and scalarCopy. Global sibling tests pass because both resolve against same cloned globals slice. Single local closure tests pass because there is no sibling alias to preserve.')
review=dict(case_id='S073',reviewer='Codex /root',full_read=dict(line_ranges=[[1,16418]],steps=93,unread=[],metadata_read=True,note='All retained messages/reasoning/commands/outputs and metadata read; tool-truncated frame discussion reread4300–4360. OwnCAS originalsharedlocal tests inspected after full trajectory; markedrepo_unseen.'),evaluation_families=[family],materials=materials,recipes=recipes,
            agent_process=dict(joint_attempt='absent',explanations=[
                dict(label='state_identity_not_transferred',support='direct',interpretation='43 writes Clone composite with two global mutators and Clone singlecapturedclosure. They coexist in the same test-generation call but never share capturedlocal in one Clone test. Full originalVM sharedcell reuse wasread7;20 even explicitly says preserveFreepointer sharing, yet27newcellperFree bypasses this requirement.',refs=[command(43,'func TestCompiled_Clone_CompositeRecursiveIsolation'),command(43,'func TestCompiled_Clone_ClosureIsolation'),reasoning(20,'the copy should probably preserve that sharing'),command(27,'cl.Free[i] = &ObjectPtr{Value: &v}')]),
                dict(label='independent_feature_checklist',support='direct',interpretation='60/64/72 systematically tickoff localcaptures,recursivecontainers,Clone,cyclehandling after separate tests.64adds more transfer/returnedarray cases and73modulemap with two read-only closures, but no siblingwriteobservedthroughsamecaptureafterClone. Coverage checklist misses the relation between alreadytested features.',refs=[reasoning(64,'recursive clone'),command(73,'m := {"add": func(x) { return x + base }, "mul": func(x) { return x * base }}'),reasoning(72,'clone handles cycle via map.')]),
                dict(label='correct_test_expectation_repairs',support='direct',interpretation='46 reportsClone3vs1,2vs1,11vs1;49debug proves actualsnapshotcopy,50correctly explains current valuesmustcopy;52fixesexpectedseed. These were wrong initial test expectations, not lost correct witnesses for the heldout sharedlocalalias bug.54removesforeignglobal-index test but that is a separate unresolvedproblem, not this failedfamily.',refs=[output(46,'Actual:   11'),output(49,'origx=1 clonex=2'),reasoning(50,'That\'s actually correct behavior!')]),
                dict(label='green_suite_as_completion_signal',support='direct',interpretation='91 late discussion explicitly revisits destinationglobals and changes nothing, then all33authoredtests/stockpass. No budgetstop; taskendsvoluntarily93. Exact sharedlocal obligation was considered20 but not operationalized. Longcontext167218 alone does not proveforgetting.',refs=[reasoning(91,'globals resolve against the destination instance'),output(91,'nothing to commit, working tree clean'),reasoning(93,'Everything is committed.')])],forgetting_assessment='counterevidence'),
            prior_record_corrections=['KnowncaseT13 retainedexplicitly, notindependentdiscovery.','Oldchosenstocksharedlocal map is one strong route, but pureauthored localfactory+globalmutator+Clone materials and modulemap route alsoavailable.','Stock exactsourcevm_test wasnotread byAgent; fullsuiterun is executioncontext, notsourcevisibility.','InitialwrongseedClone assertions corrected52 are legitimate oraclecorrection; do notclassifyasweakenedsharedlocalwitness.','Existingtwofunctions referGLOBAL n; merely wrappingcontainer doesnotintroduceLOCALsharedcell. Need onefactoryforall siblings; movingeachintoitsownfactory remainsinvalid.'],uncertainties=['Allsourcepackages are manually checked assemblies; synthesizedvariant tests were notnewlyexecuted inthisaudit. StockRindirect implies samealiasbugviaindirecthelpers andrequirespreservingcapturegraph; itisnotliterallytheofficialboxprogram.'])
(directory/'manual_review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
(directory/'reviewer_notes.txt').write_text('Full16418lines/93steps+metadata read. KnownT13, one supportedheldoutsharedlocalClonefamily. Globalpair+Clone andonecapture+Cloneexecuted43/52, butneverdistinctsiblingssharelocalafterClone.20explicitsharedFreeidentity idea27allocatesfreshcell. Pureagenttwo-wayassembly + originalstockmap(expected6) + distinctstockindirecthelper(expected20) + source-modulelocalmap alternatives. Incorrectseedassertionscorrected52legit, notweakenedwitness.\n')
(directory/'reading_status.json').write_text(json.dumps(dict(case_id='S073',reviewer='root',fulltext_ranges_read=[[1,16418]],next_line=16419,metadata_read=True),indent=2)+'\n')
