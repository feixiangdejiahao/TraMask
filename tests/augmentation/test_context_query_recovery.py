from augmentation.context_query_recovery import directory_members, serve_queries


def test_directory_query_is_bounded_to_requested_public_subtree(tmp_path):
    (tmp_path/"src").mkdir()
    (tmp_path/"other").mkdir()
    (tmp_path/"src/a.ts").write_text("function wanted() {}\n")
    (tmp_path/"other/b.ts").write_text("function wanted() {}\n")
    case={"repository":str(tmp_path)}
    base={"source_file_index":["src/a.ts","other/b.ts"],"validation_tests":[]}
    q={"kind":"search","path":"src","text":"wanted"}
    answer=serve_queries(case,base,[],[q],history_allowed=False)[0]["answer"]
    assert [x["path"] for x in answer["matches"]]==["src/a.ts"]


def test_directory_recovery_does_not_enable_parent_or_secret_search(tmp_path):
    case={"repository":str(tmp_path)}
    base={"source_file_index":[]}
    for path in ["..",".env","/tmp"]:
        assert directory_members(case,base,{"kind":"search","path":path}) is None
