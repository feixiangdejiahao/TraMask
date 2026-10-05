from scripts.normalize_trajectory_gap_pilot_transport import normalize_test


def test_python_only_whitespace_preserves_ast():
    row={'rewritten_test':'def test_x():\n    assert " x ".strip() == "x"\n\n','imports':[]}
    new,changes=normalize_test(row,'python',[])
    assert changes and new['rewritten_test']==row['rewritten_test'].rstrip()
    assert row['rewritten_test'].endswith('\n\n')


def test_extra_definition_is_not_recovered():
    row={'rewritten_test':'def test_x():\n    pass\ndef helper():\n    pass\n','imports':[]}
    assert normalize_test(row,'python',[])[0]==row


def test_exact_import_only():
    binding={'module':'../../actions/index.ts','imported_name':'transform','name':'transform','source_path':'x.ts'}
    exact={k:v for k,v in binding.items() if k!='source_path'}
    row={'rewritten_test':'irrelevant','imports':[exact]}
    assert normalize_test(row,'typescript',[binding])[0]['imports']==['transform']
    bad=dict(exact,module='wrong')
    assert normalize_test(dict(row,imports=[bad]),'typescript',[binding])[0]['imports']==[bad]
    extra=dict(exact,hidden='bad')
    assert normalize_test(dict(row,imports=[extra]),'typescript',[binding])[0]['imports']==[extra]
