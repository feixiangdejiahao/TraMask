from relation_search.linked_document_context import DocumentText,documentation_url


def test_document_extraction_excludes_navigation_and_scripts():
    parser=DocumentText();parser.feed('<nav>menu</nav><main><article><h1>Protocol</h1><p>First rule.</p><script>hidden</script><p>Second rule.</p></article></main>')
    text=parser.text()
    assert 'First rule.' in text and 'Second rule.' in text
    assert 'menu' not in text and 'hidden' not in text


def test_source_links_to_issue_discussions_and_code_are_not_documents():
    assert documentation_url('https://spec.example.org/protocol/#fields')=='https://spec.example.org/protocol/'
    assert documentation_url('https://example.org/project/issues/123') is None
    assert documentation_url('https://example.org/project/blob/main/fix.py') is None
    assert documentation_url('https://name:secret@example.org/spec') is None
