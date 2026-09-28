def span(left, right):
    if left < 0 or right < 0:
        raise ValueError("negative")
    return left == right


def test_span():
    observed = span(2, 5)
    assert observed is False
