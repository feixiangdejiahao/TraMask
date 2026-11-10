import json
from pathlib import Path

directory = Path(__file__).parent
case = json.loads((directory / 'case.json').read_text())
failed = json.loads((directory / 'evaluation_failures.json').read_text())['failed_tests']


def command(step, quote):
    return dict(step=step, call=0, channel='command', quote=quote)


def output(step, quote, call=0):
    return dict(step=step, call=call, channel='output', quote=quote)


def reasoning(step, quote):
    return dict(step=step, channel='reasoning', quote=quote)


materials = []


def material(mid, kind, availability, unit, refs, artifact='', symbol='', origin='agent_authored'):
    materials.append(dict(id=mid, kind=kind, origin=origin, availability=availability,
                          unit=unit, supports=['preserve_reset_across_consumers_and_fit_boundary'],
                          refs=refs, artifact=artifact, symbol=symbol))


material('TstyleReset', 'agent_validation', 'executed_pass',
         'Complete correctly asserted outerred+embeddedreset reopening through Style.Truncate5 of six visible characters. No ordinaryStyled call afterPreserveResets.',
         [command(24, 'func TestStyleTruncatePreserveResets'), command(24, 'String("foo\\x1b[0mbar").Foreground(ANSIColor(1)).PreserveResets()'), output(24, '--- PASS: TestStyleTruncatePreserveResets')], 'truncate_test.go', 'TestStyleTruncatePreserveResets')
material('ToutputReset', 'agent_validation', 'executed_pass',
         'Output defaulttrue OR per-calltrue with reset-between-text; truncates10 visible chars to7 and exactassertreopen.',
         [command(24, 'func TestOutputTruncatePreserveResetsDefault'), command(24, 'TruncateOptions{PreserveResets: true}'), output(24, '--- PASS: TestOutputTruncatePreserveResetsDefault')], 'truncate_test.go', 'TestOutputTruncatePreserveResetsDefault')
material('TansiReset', 'agent_validation', 'executed_pass',
         'Primitive ANSI preserve true/false and ESC[m exactoutput at width7/10chars; corrected wo-width15legit, notweakenedwitness.',
         [command(14, 'name: "preserve resets"'), command(14, 'name: "reset esc m"'), output(32, '--- PASS: TestTruncateANSI/preserve_resets')], 'ansi/ansi_test.go', 'TestTruncateANSI')
material('Tmultiple', 'agent_validation', 'executed_pass',
         'Accumulated bold/red with innerreset, actual prefix exactassert8chars; extraexpectedcharacters32corrected34forlegitimatewidthcount.',
         [command(32, 'func TestTruncateANSIMultipleResets'), output(34, 'ok')], 'ansi/ansi_test.go', 'TestTruncateANSIMultipleResets')
material('Ttoggle', 'agent_validation', 'executed_pass',
         'PreserveResets method checkedONLY boolean on plainhello-world Style; no output/assertreset.',
         [command(24, 'func TestStylePreserveResets'), command(24, 'if !s.preserveResets'), output(65, 'ok')], 'truncate_test.go', 'TestStylePreserveResets')
material('Tinherit', 'agent_validation', 'executed_pass',
         'Output.String inheritance checkedONLY boolean, plainhello; no foreground/resetrendering.',
         [command(24, 'func TestOutputStringInheritsPreserveResets'), command(24, 's := o.String("hello")'), command(24, 'if !s.preserveResets'), output(65, 'ok')], 'truncate_test.go', 'TestOutputStringInheritsPreserveResets')
material('TtemplateReset', 'agent_validation', 'executed_pass',
         'Output.TemplateFuncs defaulttrue with reset source only goes through lowercase truncate7, not Bold rendering.',
         [command(24, 'func TestOutputTemplateFuncsPropagatesDefault'), command(24, '{{ truncate 7 "\\x1b[31mhello\\x1b[0mworld" }}'), output(65, 'ok')], 'truncate_test.go', 'TestOutputTemplateFuncsPropagatesDefault')
material('TtemplateTrunc', 'agent_validation', 'executed_pass',
         'Template upper/lower truncation rendering harness with leadingSGR and noinnerreset.',
         [command(24, 'func TestOutputTemplateFuncsTruncate'), command(24, '{{ Truncate 8 "..." "\\x1b[31mhello world" }}'), output(65, 'ok')], 'truncate_test.go', 'TestOutputTemplateFuncsTruncate')
material('Tfits', 'agent_validation', 'executed_pass',
         'Plain primitive fits5, laterhello width10 tail3 fitsremaining; ordinary output identity asserted, no reset/preserve combination.',
         [command(14, 'name: "fits"'), command(38, 'func TestNoTailWhenTextFitsRemaining'), output(38, 'ok')], 'ansi/ansi_test.go;truncate_test.go', 'TestTruncateANSI/fits;TestNoTailWhenTextFitsRemaining')
material('PstyleReset', 'temporary_probe', 'executed_output',
         'Go verification program actual complete Style.Truncate preserve5 output, same shape independent temporarysource.',
         [command(59, 'termenv.String("foo\\x1b[0mbar").Foreground(termenv.ANSIColor(1)).PreserveResets().Truncate(5'), output(59, 'Style.Truncate preserve:')], '/tmp/verify.go')
material('PoutputReset', 'temporary_probe', 'executed_output',
         'Go verificationprogram defaulttrueOutput.Truncate7 and primitive preserve7, same historicalbody with raw outputoracle available.',
         [command(59, 'fmt.Printf("Output.Truncate: %q'), command(59, 'o.Truncate("\\x1b[31mhello\\x1b[0mworld", 7'), output(59, 'Output.Truncate:')], '/tmp/verify.go')
material('RstyleWidth', 'repo_test', 'read_only',
         'Original Style API chain fixture HelloWorld+Bold+Foreground; onlywidthchecks. Read5. Usablecarrier, requiresnewresetoracle fromtask/Agent.',
         [output(5, 'func TestStyleWidth'), output(5, 's = s.Foreground(TrueColor.Color("#abcdef"))')], 'style_test.go', 'TestStyleWidth', 'repo_preexisting')
material('Rtemplate', 'repo_test', 'read_only',
         'Original template evaluation plus goldencomparison harness read5; concrete Bold/style helper consumers, currentlyplaincontent.',
         [output(5, 'func TestTemplateFuncs'), output(5, 'tpl.Execute(&buf, nil)'), output(5, 'if !bytes.Equal(buf.Bytes(), expected)')], 'templatehelper_test.go', 'TestTemplateFuncs', 'repo_preexisting')
material('RtemplateNested', 'fixture_or_snapshot', 'read_only',
         'Original templatefile read10 nested Background→Foreground andBold; nested style output introducesresetfollowedouterconsumer naturally.',
         [output(10, '{{ Foreground "#00ffff" (Background "#ff00ff" "Cyan on Magenta Bg") }}'), output(10, '{{ Bold "Bold" }}')], 'testdata/templatehelper.tpl', origin='repo_preexisting')
material('Rgolden', 'fixture_or_snapshot', 'read_only',
         'Original goldenANSI nestedstylehasinnerreset+outerfinalreset, andsimpleBold expectedopen/text/reset, allactuallyprinted10. Add preserve defaultandexpectouterreopen.',
         [output(10, '\x1b[96m\x1b[105mCyan on Magenta Bg\x1b[0m\x1b[0m'), output(10, '\x1b[1mBold\x1b[0m')], 'testdata/templatehelper_ansi.txt', origin='repo_preexisting')
material('Dstyled', 'implementation', 'read_only',
         'Original Styled takesexplicitcontentandwrapsstyles; original String delegatesStyled. Read4; finalpatch leavesbothunchanged.',
         [output(4, 'func (t Style) Styled(s string) string'), output(4, 'return t.Styled(t.string)'), output(4, 'return fmt.Sprintf("%s%sm%s%sm", CSI, seq, s, CSI+ResetSeq)')], 'style.go', 'Style.Styled', 'repo_preexisting')
material('Dprofile', 'implementation', 'read_only',
         'Original Profile.String andOutput wrappingtype carrier foractualrenderingcheck;read4call1.',
         [output(4, 'func (p Profile) String(s ...string) Style', 1)], 'profile.go', 'Profile.String', 'repo_preexisting')
material('Doutput', 'implementation', 'written_unexecuted',
         'New Output.String actuallysetsflagandTruncateORsoptions. Fieldpropagationcorrectbutconsumerignoresflag; do not incorrectlyreportflagnottransferred.',
         [command(20, 'st.preserveResets = o.preserveResets'), command(20, 'opts.PreserveResets = o.preserveResets || opts.PreserveResets')], 'output.go')
material('DfitReturn', 'implementation', 'written_unexecuted',
         'Primitive discardsprocessedreopens if !truncate, returningoriginals. Concretebranchneededfortinyinput/largewidth.',
         [command(13, 'if !truncate {\n\t\treturn s\n\t}')], 'ansi/ansi.go', 'TruncateANSI')
material('Qrender', 'reasoning', 'reasoning_only',
         'Explicitscopechoice: Styled unchanged, preserveonlyTruncate;45nearendrecognizestemplateStringignoresflagbutcallspropagationmeaningful.',
         [reasoning(12, '`Styled` itself doesn\'t need to change'), reasoning(45, 'The `Styled` method doesn\'t use preserveResets.')])
material('Qfit', 'reasoning', 'reasoning_only',
         '40and60exactlyanalyze preserveplusinnerresetwithfit/no-truncation andexplicitlyapproveunchangedresult;executedproofnotpresent.',
         [reasoning(40, 'Output.Truncate` with preserve-resets and a string that fits but has internal resets'), reasoning(60, 'we do NOT re-open after resets'), reasoning(60, 'no truncation means no modification')])
material('Qcompound', 'reasoning', 'reasoning_only',
         'Compound reset parserwasexplicitlyreasoned35/40with1;0and0;31; not executedthroughStyled.',
         [reasoning(40, '`\\x1b[1;0m`'), reasoning(40, '`\\x1b[0;31m`')])
material('I1', 'issue_or_documentation', 'read_only',
         'Taskrequiresreopenwheneverpreserveenabledandalltemplatehelpers; noonly-if-content-was-shortenedexception.',
         [dict(channel='issue', path=case['issue'], quote='When preserve-resets is enabled, re-open the enclosing style after each reset run.'), dict(channel='issue', path=case['issue'], quote='propagates the default to all template helpers')], 'instruction.md', origin='issue')


def slot(role, alternatives):
    return dict(role=role, alternatives=[[m] for m in alternatives])


recipes = []


def recipe(rid, gap, slots, compatibility, additions, qualification='requires_transfer'):
    recipes.append(dict(id=rid, gap=gap, qualification=qualification, slots=slots,
                        forbidden_pairs=[], compatibility=compatibility, semantic_additions=additions))


recipe('R1', 'G1', [slot('correctouterstyle+innerresettestandoracle', ['TstyleReset', 'PstyleReset']), slot('ordinary rendering consumer', ['Dstyled', 'RstyleWidth', 'Ttoggle']), slot('contract', ['I1'])],
       'Keep existingtext/reset/red/PreserveResets, replace truncationbyString orStyled. Because nocharactersremoved,thefullbarshouldsurviveandredmustreopen. Translateexistingprefixoracletofulltext.',
       ['Use ordinaryrenderingconsumer ratherthanTruncate; addfullbarwherepreviouslywidth5cutr.'])
recipe('R2', 'G1', [slot('raw reset andexactreopenoracle', ['TansiReset', 'Tmultiple', 'ToutputReset', 'PoutputReset']), slot('Styled consumer', ['Dstyled', 'RstyleWidth', 'Ttoggle']), slot('contract', ['I1'])],
       'Move rawembeddedreset intoordinaryStylecontent, callPreserveResets andStyled/String. Do notpreapplyrawouterstyle twice; originalStyledsuppliesoutersequence.',
       ['Translate rawSGR fixture toStyleAPIandtestactualrendering.'])
recipe('R3', 'G1', [slot('existing Style preservefixture', ['TstyleReset', 'PstyleReset']), slot('compoundreset specification', ['Qcompound']), slot('renderingconsumer', ['Dstyled', 'Ttoggle']), slot('contract', ['I1'])],
       'Replace inner0mbyalreadyreasoned1;0m/0;31m/shortm, useStyledconsumer andsameouterreopenoracle. Compoundformnotrequiredtorevealbasicignoredflagbutistheofficialthirdfailingvariant.',
       ['InstantiatehistoricallyreasonedcompoundresetinsideexistingStylefixture.'])
recipe('R4', 'G2', [slot('Output.String defaults', ['Tinherit', 'Doutput']), slot('resetcontentandoracle', ['TstyleReset', 'PstyleReset', 'TansiReset', 'ToutputReset']), slot('renderingconsumer', ['Dstyled', 'RstyleWidth']), slot('contract', ['I1'])],
       'KeepNewOutputdefaulttrueanduseo.String(reset-containingtext).Foreground(...).String/Styled. Checkingfieldaloneinsufficient;expectouterSGRreopenafterinnerreset.',
       ['TransferexistingembeddedresetinputandsemanticoracleintoOutput.Stringinheritancetest.'])
recipe('R5', 'G2', [slot('Outputresetprogram', ['PoutputReset']), slot('Styleconsumer', ['TstyleReset', 'Dstyled']), slot('contract', ['I1'])],
       'ReuseexistingNewOutputWithPreserveResets(true),getstyleviao.Stringandrendernormally, retainrawreopenoracle. NoadditionalAPItestfile required.',
       ['ConnectOutputfactorywithordinaryStyleconsumer ratherthanOutput.Truncate.'])
recipe('R6', 'G3', [slot('templatehelper harness', ['TtemplateReset', 'TtemplateTrunc', 'Rtemplate']), slot('embeddedreset input+reopenoracle', ['TstyleReset', 'TansiReset', 'ToutputReset', 'PstyleReset']), slot('Bold/style operation', ['RtemplateNested', 'Rgolden']), slot('contract', ['I1'])],
       'UseOutput.TemplateFuncsdefaulttruebuttemplate{{Bold .}}orForegroundonresetcontent,withnotruncatehelper. Reuseexistinginnerresetandexactouterreopenexpectation. Otherstylehelperssameconsumer.',
       ['Transferresetinputintosiblingtemplateconsumerandassertactualoutput, notflag.'])
recipe('R7', 'G3', [slot('existing nestedstyle source', ['RtemplateNested']), slot('expectedresetlayout', ['Rgolden']), slot('preservedefaulttemplateharness', ['TtemplateReset', 'TtemplateTrunc']), slot('contract', ['I1'])],
       'OriginalForeground(Background(...))producesinnerresetwithinouterstyle; enableOutputdefaulttrueandexpectoriginalouterSGRreopenafterinnerresetbeforeouterfinalreset. Additionalplainbafterresetavoidsredundant-onlydifference.',
       ['Useoldrepo nestedhelper fixtureplusnewOutputflag; addpostresetvisiblecontentifneeded.'])
recipe('R8', 'G4', [slot('reset preserveOutputtest', ['ToutputReset', 'PoutputReset']), slot('fit-boundary carrier', ['Tfits', 'Qfit', 'DfitReturn']), slot('contract', ['I1'])],
       'Onlyincreaserequestedwidth7toatleast10forhelloworldorusehistoricala-reset-bwidth10. Keepdefaulttrue/per-calltruebothbranchesandassertreopen/finalresetdespitenoshortening.',
       ['Transferno-truncationwidthconditionintoexistingresettest; inputandoraclealreadyknown.'])
recipe('R9', 'G4', [slot('sameprimitive behavior test', ['TansiReset', 'Tmultiple', 'TstyleReset']), slot('Outputwrapper', ['ToutputReset', 'PoutputReset', 'Doutput']), slot('fitcondition', ['Tfits', 'Qfit']), slot('contract', ['I1'])],
       'MoveexistingreopeninputthroughOutputwrapperatlargewidth,defaulttrueORoptsPreserveResets. Originalprimitive/no-tailfitreturnsoriginalandlosesprocessedreopens; finalresetassertmayalsoneedtask-derivedexpectation.',
       ['Changeonlywidth/consumerboundary;preserveinputresetrelationandsemanticoracle.'])

by_suffix = lambda suffix: [f['name'] for f in failed if f['name'].endswith(suffix)]
families = [
    dict(id='G1', failed_tests=by_suffix('.TestMarsPreserveResets_ReappliesAfterReset')+by_suffix('.TestMarsPreserveResets_CompoundReset'),
         contract='Style.PreserveResets changes ordinary Styled/String output for allresetforms, not only truncatedoutput.',
         missing_joint_test='Style with outergreen,embedded0m/shortm/compound1;0;31m,PreserveResets,ordinaryStyled; exactassertouterreopen.',
         classification='basic_feature_failure', verifier_validity='supported', joint_attempt='absent'),
    dict(id='G2', failed_tests=by_suffix('.TestMarsPreserveResets_OutputOptionAffectsOutputString'),
         contract='Output.String inheritedpreserveflagmusthavevisibleeffectthroughnormalStyledconsumer.',
         missing_joint_test='Outputdefaulttrue→String(embeddedreset).Foreground(...).Styled/String; assertreopen, notjustprivateboolean.',
         classification='weak_oracle', verifier_validity='supported', joint_attempt='weak_oracle'),
    dict(id='G3', failed_tests=by_suffix('.TestMarsPreserveResets_TemplateFuncsPreserveResets'),
         contract='OutputdefaultappliestoBoldandotherstylehelperswithoutneedingTruncatehelper.',
         missing_joint_test='Template{{Bold .}}witha-reset-bandOutputpreserve=true; assertboldreopenafterreset.',
         classification='untested_interaction', verifier_validity='supported', joint_attempt='absent'),
    dict(id='G4', failed_tests=by_suffix('.TestMarsOutputTruncate_OptsOverridesDefault')+by_suffix('.TestMarsOutputTruncate_UsesPreserveResets'),
         contract='PreserveResets remainsactivewhenrequestedwidthdoesnotshorteninput; defaultORoptsbothworkandactiveSGRfinalreset.',
         missing_joint_test='ExistingOutput.Truncate resetinputwithwidth>=visibleinputwidth,retainreopenoracleandfinalresetexpectation.',
         classification='different_stimulus', verifier_validity='supported', joint_attempt='absent')
]
review = dict(case_id='S080', reviewer='Codex /root',
              full_read=dict(line_ranges=[[1,13575]], steps=66, unread=[], metadata_read=True,
                             note='Allretainedtextreadsequentially;tooltruncation4020-4170reread. Originalharnesselisions5/44arenotclaimedvisible.'),
              evaluation_families=families, materials=materials, recipes=recipes,
              agent_process=dict(joint_attempt='weak_oracle', explanations=[
                  dict(label='feature_scope_restricted_to_truncation', support='direct',
                       interpretation='12decidesStyleddoesnotneedchange.45explicitlynoticesStylerenderingignoresflag,buttreatsfieldpropagationasharmlessmeaningful.60rereadsspecandassertsdone. ThismissesordinaryStyledandallstylehelperconsumers.',
                       refs=[reasoning(12, '`Styled` itself doesn\'t need to change'), reasoning(45, 'The `Styled` method doesn\'t use preserveResets.'), reasoning(60, 're-open the enclosing style after each reset run')]),
                  dict(label='field_inheritance_substituted_for_behavioral_validation', support='direct',
                       interpretation='Output.Stringtestonlychecksprivateboolean;PreserveResetstestlikewise. SemanticreopenoracleexistsinStyle.TruncateandOutput.TruncatebutisnottransferredtoString/StyledorBold.',
                       refs=[command(24, 'if !s.preserveResets'), command(24, 'func TestStyleTruncatePreserveResets'), command(24, 'func TestOutputTemplateFuncsPropagatesDefault')]),
                  dict(label='identity_on_no_truncation_assumption', support='direct',
                       interpretation='40and60exactlyrevisitpreserve+innerreset+fits andacceptunchangedasnaturaltruncationsemantics. Contrarytounqualifiedtaskpreserverule;inputnotforgotten. No actualruntimecounterwitnessisclaimed.',
                       refs=[reasoning(60, 'we do NOT re-open after resets'), reasoning(60, 'no truncation means no modification')]),
                  dict(label='inferred_upstream_behavior_over_local_contract', support='inferred',
                       interpretation='8/11/12/28/30/36/37repeatedmemory-basedupstreamreconstructionsdespitenonetwork7. Largeattentiontounrelatedtailfitsemantics37/38;doesnotestablishcausalforgettingbutshowsimplementation-drivenoracledecisions.',
                       refs=[reasoning(8, 'I know the actual upstream implementation quite well.'), reasoning(37, 'the hidden tests are the upstream tests'), command(38, 'name: "tail reserves width"')])
              ], forgetting_assessment='counterevidence'),
              prior_record_corrections=['Notall6failuresaremissingcombinations:ordinaryStyle.PreserveResetsbasicsemanticsneverimplemented;Outputflagtransferitselfiscorrect,itsrenderingconsumerignoresflag.',
                                        'Actualcorrectreopenoraclealreadyexistsinthreemethodlayersandtemporaryverifyprogram;neededtransfersareconsumerselectionandfitboundary.',
                                        '15/34wo/bawidthoraclecorrectionsarelegitimate,notweakenedbugwitnesses.37/38tailsemanticrevisionisindependentofthesesixfailures.',
                                        'Originaltemplatefixturesandgoldenswereactuallyread5/10;donotmarkrepo_unseen. NooutsidehistoricaltestfromS079isused.'],
              uncertainties=['Alternativeassembliesmanuallycheckedbutnotnewlysynthesizedandexecuted;fitvariantknownfromreasoningisnotlabeledexecuted.',
                             'UpstreammemoryclaimsareAgentclaims,notverifiedsourcefacts;analysisuseslocalissueandactualverifierinstead.'])
(directory / 'manual_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2)+'\n')
(directory / 'reviewer_notes.txt').write_text('Full13575lines/66steps+metadataread. 6fails4families:basicordinaryStyled(2);Output.Stringboolean-onlyweakoracle(1);Boldtemplateresetabsent(1);OutputTruncatepreserve+fitboundary(2). CorrectreopenoraclealreadyexistsStyleTruncate/OutputTruncate/primitiveandtmpverify. Explicit12Styledunchanged45ignoreflagharmless60fitsunchangedcounterforget. Oldnestedtemplatefixture/goldensactuallyread5/10additionalrepo+Agentroute. Noexternalnewexecution.\n')
(directory / 'reading_status.json').write_text(json.dumps(dict(read_lines=13575,total_lines=13575,steps=66,metadata_read=True),indent=2)+'\n')
