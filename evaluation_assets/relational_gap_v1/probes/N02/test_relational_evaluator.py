"""Manual retrospective ground-truth check; excluded from generation."""
import httpx
from httpx._content import IteratorByteStream
import pytest

HEADERS = {"Content-Type": "multipart/mixed; boundary=BOUNDARY"}
VALID = b"--BOUNDARY\r\nX: 1\r\n\r\nx\r\n--BOUNDARY--\r\n"
INVALID = b"--BOUNDARY\r\nX: 1\r\n\r\nx"


def response(body):
    stream = IteratorByteStream(body[index:index + 3] for index in range(0, len(body), 3))
    return httpx.Response(200, stream=stream, headers=HEADERS)


def test_control_normal_stream_closes():
    r = response(VALID)
    assert len(list(r.iter_multipart())) == 1
    assert r.is_closed


def test_control_invalid_memory_raises():
    r = httpx.Response(200, content=INVALID, headers=HEADERS)
    with pytest.raises(httpx.DecodingError):
        list(r.iter_multipart())


def test_gap_invalid_stream_closes():
    r = response(INVALID)
    with pytest.raises(httpx.DecodingError):
        list(r.iter_multipart())
    assert r.is_closed
