from experimental.semantic_transport.contracts import extract_contracts


def evidence(code):
    return {'files': [{'path': 'subject', 'snippets': [{'start_line': 20, 'code': code}]}]}


def test_python_uses_documentation_not_implementation_as_oracle_evidence():
    result = extract_contracts(evidence('''def project(x: int) -> int:
    """Preserve the input's magnitude."""
    return x + 927351
'''), 'python')
    text = str(result)
    assert 'Preserve' in text and 'project(x: int)' in text
    assert '927351' not in text and 'return x' not in text
    assert result['declarations'][0]['line'] == 20


def test_go_comments_signatures_and_types_are_preserved_without_body():
    result = extract_contracts(evidence('''package p
// Read returns the accumulated elements in order.
func (b *Box) Read() []int { return []int{729314} }
'''), 'go')
    assert len(result['declarations']) == 1
    assert 'Read returns' in str(result)
    assert 'Read() []int' in str(result)
    assert '729314' not in str(result)


def test_typescript_contract_is_not_a_recorded_candidate_answer():
    result = extract_contracts(evidence('''/** Return a fresh sequence. */
function copy(x: number[]): number[] { return [93751]; }
'''), 'typescript')
    assert 'fresh sequence' in str(result)
    assert '93751' not in str(result)


def test_contract_budget_is_deterministic_and_records_omissions():
    source = evidence('def one(x):\n    """long contract"""\n    return x\n')
    first = extract_contracts(source, 'python', max_chars=1)
    assert first == extract_contracts(source, 'python', max_chars=1)
    assert first['declarations'] == []
    assert first['omitted'][0]['reason'] == 'contract_context_budget'
