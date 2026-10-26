from __future__ import annotations

import asyncio
import typing

import pytest

import httpx
from httpx._content import AsyncIteratorByteStream, IteratorByteStream


def test_multipart_response_in_memory() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=(
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Hello, world!\r\n"
            b"--BOUNDARY\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b'{"key": "value"}\r\n'
            b"--BOUNDARY--\r\n"
        ),
    )

    parts = list(response.iter_multipart())

    assert len(parts) == 2
    assert parts[0].headers["Content-Type"] == "text/plain"
    assert parts[0].content == b"Hello, world!"
    assert parts[1].headers["Content-Type"] == "application/json"
    assert parts[1].content == b'{"key": "value"}'
    assert all(isinstance(part.headers, httpx.Headers) for part in parts)

    # In-memory bodies are repeatable.
    assert len(list(response.iter_multipart())) == 2


def test_multipart_response_closing_boundary_only() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=b"--BOUNDARY--\r\n",
    )
    assert list(response.iter_multipart()) == []


@pytest.mark.parametrize("line_ending", [b"\r\n", b"\n", b"\r"])
def test_multipart_response_line_endings(line_ending: bytes) -> None:
    content = b"".join(
        [
            b"--BOUNDARY" + line_ending,
            b"Content-Type: text/plain" + line_ending,
            line_ending,
            b"line one" + line_ending,
            b"line two" + line_ending,
            b"--BOUNDARY--" + line_ending,
        ]
    )
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=content,
    )
    parts = list(response.iter_multipart())
    assert len(parts) == 1
    assert parts[0].content == b"line one" + line_ending + b"line two"


def test_multipart_response_crlf_split_across_chunks() -> None:
    body = b"--BOUNDARY\r\nContent-Type: text/plain\r\n\r\nHello\r\n--BOUNDARY--\r\n"

    # Split every CRLF into two separate chunks, splitting between \r and \n.
    chunks: list[bytes] = []
    index = 0
    while index < len(body):
        crlf = body.find(b"\r\n", index)
        if crlf == -1:
            chunks.append(body[index:])
            break
        chunks.append(body[index : crlf + 1])
        chunks.append(body[crlf + 1 : crlf + 2])
        index = crlf + 2

    def stream() -> typing.Iterator[bytes]:
        yield from chunks

    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        stream=IteratorByteStream(stream()),
    )
    parts = list(response.iter_multipart())
    assert len(parts) == 1
    assert parts[0].content == b"Hello"


def test_multipart_response_streaming_consumes_and_closes() -> None:
    body = b"--BOUNDARY\r\nContent-Type: text/plain\r\n\r\nHello\r\n--BOUNDARY--\r\n"

    def stream() -> typing.Iterator[bytes]:
        for index in range(0, len(body), 3):
            yield body[index : index + 3]

    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        stream=IteratorByteStream(stream()),
    )

    parts = list(response.iter_multipart())
    assert len(parts) == 1
    assert response.is_stream_consumed is True
    assert response.is_closed is True

    with pytest.raises(httpx.StreamConsumed):
        list(response.iter_multipart())


def test_multipart_response_aiter_multipart() -> None:
    body = b"--BOUNDARY\r\nContent-Type: text/plain\r\n\r\nHello\r\n--BOUNDARY--\r\n"

    async def stream() -> typing.AsyncIterator[bytes]:
        for index in range(0, len(body), 2):
            yield body[index : index + 2]

    async def main() -> None:
        response = httpx.Response(
            200,
            headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
            stream=AsyncIteratorByteStream(stream()),
        )
        parts = [part async for part in response.aiter_multipart()]
        assert len(parts) == 1
        assert parts[0].content == b"Hello"
        assert response.is_stream_consumed is True
        assert response.is_closed is True

        with pytest.raises(httpx.StreamConsumed):
            async for _ in response.aiter_multipart():
                pass

    asyncio.run(main())


def test_multipart_response_preamble_and_epilogue() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=(
            b"preamble line\r\n"
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Hello\r\n"
            b"--BOUNDARY--\r\n"
            b"epilogue line\r\n"
        ),
    )
    parts = list(response.iter_multipart())
    assert len(parts) == 1
    assert parts[0].content == b"Hello"


def test_multipart_response_headers_continuation_and_duplicates() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=(
            b"--BOUNDARY\r\n"
            b"X-Custom: one\r\n"
            b" two\r\n"
            b"X-Custom: three\r\n"
            b"\r\n"
            b"Hello\r\n"
            b"--BOUNDARY--\r\n"
        ),
    )
    parts = list(response.iter_multipart())
    assert parts[0].headers.get_list("X-Custom") == ["one two", "three"]


def test_multipart_response_body_excludes_preceding_terminator() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=(
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"line one\r\n"
            b"\r\n"
            b"--BOUNDARY--\r\n"
        ),
    )
    parts = list(response.iter_multipart())
    assert parts[0].content == b"line one\r\n"


def test_multipart_response_boundary_like_content_lines() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=(
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"--BOUNDARY-not-a-delimiter\r\n"
            b"still content\r\n"
            b"--BOUNDARY--\r\n"
        ),
    )
    parts = list(response.iter_multipart())
    assert parts[0].content == b"--BOUNDARY-not-a-delimiter\r\nstill content"


@pytest.mark.parametrize(
    "content_type",
    [
        "multipart/form-data; boundary=abc",
        "multipart/mixed; boundary=abc",
        "MULTIPART/MIXED; BOUNDARY=abc",
        "multipart/mixed; boundary= abc ",
        'multipart/mixed; boundary="abc"',
        "multipart/mixed; boundary=first; boundary=abc",
        "multipart/mixed; charset=utf-8; boundary=abc",
        'multipart/mixed; boundary="a;b"',
    ],
)
def test_multipart_response_valid_content_types(content_type: str) -> None:
    from httpx._multipart import get_multipart_boundary_from_content_type

    boundary = get_multipart_boundary_from_content_type(content_type)
    assert boundary is not None
    response = httpx.Response(
        200,
        headers={"Content-Type": content_type},
        content=(b"--" + boundary + b"\r\n\r\nHello\r\n--" + boundary + b"--\r\n"),
    )
    parts = list(response.iter_multipart())
    assert len(parts) == 1
    assert parts[0].content == b"Hello"


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "multipart/",
        "multipart/mixed",
        "multipart/mixed; boundary=",
        "multipart/mixed; boundary=abc\r\n",
        "multipart/mixed; boundary==abc",
        "multipart/mixed; boundary=abc\x00def",
        "multipart/mixed; boundary=caf\xc3\xa9",
    ],
)
def test_multipart_response_invalid_content_types(content_type: str) -> None:
    response = httpx.Response(
        200,
        headers=[(b"Content-Type", content_type.encode("utf-8"))],
        content=b"--abc\r\n\r\nHello\r\n--abc--\r\n",
    )
    with pytest.raises(httpx.DecodingError):
        list(response.iter_multipart())


def test_multipart_response_malformed_preamble() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=(
            b"--BOUNDARY-not-a-delimiter\r\n--BOUNDARY\r\n\r\nHello\r\n--BOUNDARY--\r\n"
        ),
    )
    with pytest.raises(httpx.DecodingError):
        list(response.iter_multipart())


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"no boundary here",
        b"--BOUNDARY\r\n\r\nHello\r\n",
        b"--BOUNDARY\r\nHeader: value\r\n\r\n",
        b"--BOUNDARY\r\n",
    ],
)
def test_multipart_response_malformed_framing(body: bytes) -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=body,
    )
    with pytest.raises(httpx.DecodingError):
        list(response.iter_multipart())


@pytest.mark.parametrize(
    "headers",
    [
        b"Malformed Header\r\n",
        b": value\r\n",
        b"  leading whitespace\r\n",
        b"Name: value\r\n\t\r\n",
    ],
)
def test_multipart_response_malformed_headers(headers: bytes) -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "multipart/mixed; boundary=BOUNDARY"},
        content=(
            b"--BOUNDARY\r\n" + headers + b"\r\n" + b"Hello\r\n" + b"--BOUNDARY--\r\n"
        ),
    )
    with pytest.raises(httpx.DecodingError):
        list(response.iter_multipart())


def test_multipart_decoder() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        b"--BOUNDARY\r\nContent-Type: text/plain\r\n\r\nHello\r\n--BOUNDARY--\r\n",
    )
    assert len(decoder.parts) == 1
    assert decoder.parts[0].content == b"Hello"
    assert decoder.parts[0].headers["Content-Type"] == "text/plain"
    assert decoder.parts[0].data == b"Hello"


def test_multipart_decoder_iter_parts_with_bytes() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        b"--BOUNDARY\r\n\r\nHello\r\n--BOUNDARY--\r\n",
    )
    assert [part.content for part in decoder.iter_parts()] == [b"Hello"]


def test_multipart_decoder_aiter_parts_with_bytes() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        b"--BOUNDARY\r\n\r\nHello\r\n--BOUNDARY--\r\n",
    )

    async def main() -> None:
        assert [part.content async for part in decoder.aiter_parts()] == [b"Hello"]

    asyncio.run(main())


def test_multipart_decoder_sync_iteration_on_async_stream() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        AsyncIteratorByteStream(agen_bytes()),
    )
    with pytest.raises(RuntimeError):
        list(decoder.iter_parts())


def test_multipart_decoder_async_iteration_on_sync_stream() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        IteratorByteStream(iter([b"--BOUNDARY--\r\n"])),
    )

    async def main() -> None:
        with pytest.raises(RuntimeError):
            async for _ in decoder.aiter_parts():
                pass

    asyncio.run(main())


def test_multipart_part_filename() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        (
            b"--BOUNDARY\r\n"
            b'Content-Disposition: form-data; name="file"; filename="example.txt"\r\n'
            b"\r\n"
            b"Hello\r\n"
            b"--BOUNDARY--\r\n"
        ),
    )
    part = decoder.parts[0]
    assert part.filename == "example.txt"


def test_multipart_part_filename_missing() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        b"--BOUNDARY\r\nContent-Type: text/plain\r\n\r\nHello\r\n--BOUNDARY--\r\n",
    )
    assert decoder.parts[0].filename is None


def test_multipart_part_filename_without_match() -> None:
    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY",
        (b"--BOUNDARY\r\nContent-Disposition: inline\r\n\r\nHello\r\n--BOUNDARY--\r\n"),
    )
    assert decoder.parts[0].filename is None


def test_multipart_boundary_escaped_quotes() -> None:
    from httpx._multipart import get_multipart_boundary_from_content_type

    boundary = get_multipart_boundary_from_content_type(
        b'multipart/mixed; boundary="a\\"b"'
    )
    assert boundary == b'a\\"b'


async def agen_bytes() -> typing.AsyncIterator[bytes]:
    yield b"--BOUNDARY--\r\n"


def test_multipart_decoder_aiter_parts_streaming_final_drain() -> None:
    async def stream() -> typing.AsyncIterator[bytes]:
        # No trailing newline: the closing delimiter is only completed at EOF.
        yield b"--BOUNDARY\r\n\r\nHello\r\n--BOUNDARY--"

    decoder = httpx.MultipartDecoder(
        "multipart/mixed; boundary=BOUNDARY", AsyncIteratorByteStream(stream())
    )

    async def main() -> None:
        assert [part.content async for part in decoder.aiter_parts()] == [b"Hello"]

    asyncio.run(main())
