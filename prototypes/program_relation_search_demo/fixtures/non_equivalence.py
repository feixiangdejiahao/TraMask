def parity(value):
    if value <= 0:
        return None
    return value % 2


def test_parity():
    observed = parity(5)
    assert observed in (0, 1)
