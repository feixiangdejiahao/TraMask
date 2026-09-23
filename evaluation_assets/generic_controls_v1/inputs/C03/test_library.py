from library import bump_and_read

def test_separate_values():
    left, right = [3], [3]
    assert bump_and_read(left, right, 1) == 3

def test_shared_value():
    values = [3]
    assert bump_and_read(values, values, 1) == 4

def test_mutation_visible():
    left, right = [3], [3]
    bump_and_read(left, right, 2)
    assert left == [5]
