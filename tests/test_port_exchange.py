from generic_composition.corpus import build_corpus
from prototypes.port_exchange import generate


def test_different_source_producers_can_cross_the_same_argument_port(tmp_path):
    (tmp_path / 'test_port.py').write_text('''def identity(): return lambda x: x
def increment(): return lambda x: x + 1
def apply(value, operation): return operation(value)
def test_left(): assert apply(1, identity()) == 1
def test_right(): assert apply(2, increment()) == 3
''')
    corpus = build_corpus(tmp_path, 'python')
    result = generate(corpus)
    assert any(c['edits'][0]['before'] == 'identity()' and c['edits'][0]['after'] == 'increment()'
               for c in result['candidates'])
    assert result == generate(corpus)


def test_assertion_framework_actual_arguments_are_not_subject_ports(tmp_path):
    (tmp_path / 'test_port.py').write_text('''import unittest
def produce_a(): return 1
def produce_b(): return 2
class Check(unittest.TestCase):
    def test_left(self): self.assertEqual(produce_a(), 1)
    def test_right(self): self.assertEqual(produce_b(), 2)
''')
    assert not generate(build_corpus(tmp_path, 'python'))['candidates']


def test_nonclosed_expression_does_not_capture_target_local_names(tmp_path):
    (tmp_path / 'test_port.py').write_text('''def construct(x): return x
def apply(operation): return operation
def test_left(): assert apply(construct(1)) == 1
def test_right():
    private_value = factory()
    assert apply(construct(private_value)) == 2
''')
    result = generate(build_corpus(tmp_path, 'python'))
    assert not any(c['edits'][0]['after'] == 'construct(private_value)' for c in result['candidates'])


def test_same_local_spelling_does_not_authorize_a_different_binding(tmp_path):
    (tmp_path / 'test_port.py').write_text('''def construct(x): return x
def apply(operation): return operation
def test_left():
    value = 1
    assert apply(construct(value)) == 1
def test_right():
    value = 2
    assert apply(construct(value + 1)) == 3
''')
    result = generate(build_corpus(tmp_path, 'python'))
    assert result['candidates'] == []
    assert result['skipped']['source_local_requires_dependency_slice'] > 0
