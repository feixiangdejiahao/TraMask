"""Lossless, content-addressed storage for captured file and stream bytes."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


CHUNK_SIZE = 64 * 1024


class BlobStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def create(self, shared_chunks=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        chunks = self.directory / 'chunks'
        if shared_chunks is None:
            chunks.mkdir()
        else:
            chunks.symlink_to(os.path.relpath(shared_chunks, self.directory), target_is_directory=True)

    @staticmethod
    def _publish(path, data):
        if path.exists():
            return
        # Workers may produce the same chunk concurrently. Publish only after
        # writing it completely so other readers never observe partial bytes.
        with tempfile.NamedTemporaryFile(dir=path.parent) as temporary:
            temporary.write(data)
            temporary.flush()
            try:
                os.link(temporary.name, path)
            except FileExistsError:
                pass

    def put(self, data):
        digest = hashlib.sha256(data).hexdigest()
        descriptor = self.directory / digest
        if descriptor.exists():
            return digest
        chunks = []
        for start in range(0, len(data), CHUNK_SIZE):
            chunk = data[start:start + CHUNK_SIZE]
            key = hashlib.sha256(chunk).hexdigest()
            self._publish(self.directory / 'chunks' / key, chunk)
            chunks.append(key)
        self._publish(descriptor, json.dumps(chunks).encode())
        return digest

    def read(self, digest):
        chunks = json.loads((self.directory / digest).read_bytes())
        return b''.join((self.directory / 'chunks' / key).read_bytes() for key in chunks)

    def read_range(self, digest, offset, length):
        chunks = json.loads((self.directory / digest).read_bytes())
        index, within = divmod(offset, CHUNK_SIZE)
        result = []
        while length and index < len(chunks):
            with (self.directory / 'chunks' / chunks[index]).open('rb') as source:
                source.seek(within)
                data = source.read(min(length, CHUNK_SIZE - within))
            result.append(data)
            length -= len(data)
            index += 1
            within = 0
        return b''.join(result)

    def merge(self, other):
        """Link another store into this one without changing the input store."""
        same_files = other.directory.stat().st_dev == self.directory.stat().st_dev
        same_chunks = (other.directory / 'chunks').stat().st_dev == (self.directory / 'chunks').stat().st_dev

        def link(source, destination, same_device):
            if not same_device:
                if not destination.exists():
                    self._publish(destination, source.read_bytes())
                return
            try:
                os.link(source, destination)
            except FileExistsError:
                pass

        chunks = set()
        for source in other.directory.iterdir():
            if source.is_dir():
                continue
            chunks.update(json.loads(source.read_bytes()))
            link(source, self.directory / source.name, same_files)
        for key in chunks:
            link(other.directory / 'chunks' / key, self.directory / 'chunks' / key, same_chunks)
