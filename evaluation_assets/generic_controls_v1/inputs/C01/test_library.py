from library import canonical

def test_order():
    assert canonical([2, 1]) == [1, 2]

def test_duplicates():
    assert canonical([2, 1, 2]) == [1, 2, 2]

def test_copy():
    values = [2, 1]
    canonical(values)
    assert values == [2, 1]
