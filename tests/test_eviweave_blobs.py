"""Storage keeps exact versions while sharing unchanged bytes."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import random

from eviweave.blobs import BlobStore, CHUNK_SIZE
from eviweave.artifacts import relative_references, resolve_references


def test_versions_and_cross_case_chunks_are_shared_without_losing_bytes(tmp_path):
    chunks = tmp_path / 'shared'
    chunks.mkdir()
    stores = [BlobStore(tmp_path / case / 'blobs') for case in ('one', 'two')]
    for store in stores:
        store.create(chunks)
    random_bytes = random.Random(17).randbytes(CHUNK_SIZE * 32)
    versions = [random_bytes[:i * CHUNK_SIZE + 37] for i in range(32)] + [b'']

    with ThreadPoolExecutor(max_workers=2) as pool:
        digests = list(pool.map(lambda store: [store.put(v) for v in versions], stores))

    assert digests[0] == digests[1]
    for store, ids in zip(stores, digests):
        for expected, digest in zip(versions, ids):
            assert digest == hashlib.sha256(expected).hexdigest()
            assert store.read(digest) == expected
            assert store.read_range(digest, CHUNK_SIZE - 11, 30) == expected[CHUNK_SIZE - 11:CHUNK_SIZE + 19]
    stored = sum(p.stat().st_size for p in chunks.iterdir())
    assert stored < sum(map(len, versions)) // 5
    assert stores[0].directory.joinpath('chunks').resolve() == stores[1].directory.joinpath('chunks').resolve()


def test_merge_preserves_the_original_store_and_every_version(tmp_path):
    first, second = (BlobStore(tmp_path / name) for name in ('source', 'destination'))
    first.create(); second.create()
    payloads = [b'one', b'two' * CHUNK_SIZE, b'two' * CHUNK_SIZE + b'changed']
    digests = [first.put(value) for value in payloads]
    second.merge(first)
    assert [first.read(d) for d in digests] == payloads
    assert [second.read(d) for d in digests] == payloads


def test_merge_only_copies_chunks_referenced_by_the_case(tmp_path):
    shared = tmp_path / 'shared'; shared.mkdir()
    selected = BlobStore(tmp_path / 'selected'); selected.create(shared)
    unrelated = BlobStore(tmp_path / 'unrelated'); unrelated.create(shared)
    destination = BlobStore(tmp_path / 'destination'); destination.create()
    keep = selected.put(b'keep this case')
    discard = unrelated.put(b'other case only')
    destination.merge(selected)
    assert destination.read(keep) == b'keep this case'
    assert not (destination.directory / 'chunks' / discard).exists()


def test_export_preserves_json_values_and_embedded_source_errors(tmp_path):
    source = tmp_path / 'data.json'
    structure = {'source':'upstream','manifest':'v2','trajectory':'inputs.bin'}
    view = {'source':str(source), 'structure':structure,
            'embedded_inputs':[{'structure':structure,'issues':[{'source':'embedded','kind':'source_parse_error'}]}]}
    base = tmp_path / 'slicing'; base.mkdir()
    exported = relative_references(view, base)
    assert exported['structure'] == structure and exported['embedded_inputs'] == view['embedded_inputs']
    assert resolve_references(exported, base) == view


