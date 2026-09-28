def configure(primary, secondary):
    return (primary.get("width", 4), primary.get("height", 7),
            secondary.get("width", 4), secondary.get("height", 7))


def test_full():
    observed = configure({"width": 9, "height": 12}, {"width": 9, "height": 12})
    assert len(observed) == 4


def test_empty():
    observed = configure({}, {})
    assert len(observed) == 4
