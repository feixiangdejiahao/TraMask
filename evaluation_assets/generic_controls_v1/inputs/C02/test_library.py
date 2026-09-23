from library import area

def test_vertical_strip():
    assert area(1, 2) == 2

def test_horizontal_strip():
    assert area(2, 1) == 2

def test_single_cell():
    assert area(1, 1) == 1
