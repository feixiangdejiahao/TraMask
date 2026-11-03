"""Decode source text using Python's declared encoding where applicable."""
from io import BytesIO
from pathlib import PurePosixPath
import tokenize


def decode_source(path, raw):
    if PurePosixPath(path).suffix == '.py':
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        return raw.decode(encoding)
    return raw.decode('utf-8')


def decode_material(path, raw):
    """Keep readable invalid Python source while reporting its encoding error."""
    if PurePosixPath(path).suffix != '.py':
        return raw.decode('utf-8'), None
    try:
        return decode_source(path, raw), None
    except (SyntaxError, UnicodeDecodeError) as error:
        try:
            return raw.decode('utf-8'), str(error)
        except UnicodeDecodeError:
            return None, str(error)
