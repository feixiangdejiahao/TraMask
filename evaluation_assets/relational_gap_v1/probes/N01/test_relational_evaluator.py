"""Manual retrospective ground-truth check; excluded from generation."""
import httpx
import pytest


def response(chunks):
    return httpx.Response(200, content=iter(chunks),
                          headers={"Content-Type": "application/ndjson"})


def test_control_normal_stream_closes():
    r = response([b'{"a": 1}\n', b'{"b": 2}\n'])
    assert list(r.iter_json()) == [{"a": 1}, {"b": 2}]
    assert r.is_closed


def test_control_invalid_memory_raises():
    r = httpx.Response(200, content=b'{"a": 1}\nnot json\n',
                       headers={"Content-Type": "application/ndjson"})
    with pytest.raises(httpx.DecodingError):
        list(r.iter_json())


def test_gap_invalid_stream_closes():
    r = response([b'{"a": 1}\n', b'not json\n'])
    with pytest.raises(httpx.DecodingError):
        list(r.iter_json())
    assert r.is_closed
