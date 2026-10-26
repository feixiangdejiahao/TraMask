cat > tests/unit/core/test_cache.py <<'EOF'
# Copyright 2025
#
# SPDX-License-Identifier: Apache-2.0
import json
import os
import tempfile
import time

import fixtures
import testtools

from bandit.core import cache as b_cache


class BanditCacheTests(testtools.TestCase):
    def setUp(self):
        super().setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.cache_dir = os.path.join(self.tempdir, "cache")
        self.cache = b_cache.BanditCache(
            self.cache_dir, cache_key="key1", expiry_days=30
        )

    def _entry(self, path, **overrides):
        entry = {
            "path": path,
            "cache_key": "key1",
            "file_hash": "abc123",
            "file_size": 10,
            "mtime": time.time(),
            "cached_at": time.time(),
            "dependencies": [],
            "skipped": False,
            "skip_reason": None,
            "issues": [],
            "metrics": {"loc": 1},
        }
        entry.update(overrides)
        return entry

    def test_save_creates_directory(self):
        self.cache.store("/tmp/file.py", self._entry("/tmp/file.py"))
        self.cache.save()
        self.assertTrue(os.path.isdir(self.cache_dir))
        self.assertTrue(os.path.exists(self.cache.cache_path))

    def test_round_trip(self):
        self.cache.store("/tmp/file.py", self._entry("/tmp/file.py"))
        self.cache.save()
        loaded = b_cache.BanditCache(
            self.cache_dir, cache_key="key1", expiry_days=30
        )
        self.assertIn("/tmp/file.py", loaded.entries)
        self.assertEqual("abc123", loaded.entries["/tmp/file.py"]["file_hash"])

    def test_format_version_ignored(self):
        self.cache.store("/tmp/file.py", self._entry("/tmp/file.py"))
        self.cache.save()
        with open(self.cache.cache_path, "w") as f:
            json.dump({"format_version": 999, "entries": {}}, f)
        loaded = b_cache.BanditCache(self.cache_dir, cache_key="key1")
        self.assertEqual({}, loaded.entries)

    def test_corrupted_entries_discarded(self):
        self.cache.store("/tmp/good.py", self._entry("/tmp/good.py"))
        self.cache.save()
        with open(self.cache.cache_path) as f:
            data = json.load(f)
        data["entries"]["/tmp/bad.py"] = {"path": "/tmp/bad.py"}
        with open(self.cache.cache_path, "w") as f:
            json.dump(data, f)
        loaded = b_cache.BanditCache(self.cache_dir, cache_key="key1")
        self.assertIn("/tmp/good.py", loaded.entries)
        self.assertNotIn("/tmp/bad.py", loaded.entries)

    def test_corrupted_cache_file(self):
        with open(self.cache.cache_path, "w") as f:
            f.write("{broken")
        loaded = b_cache.BanditCache(self.cache_dir, cache_key="key1")
        self.assertEqual({}, loaded.entries)

    def test_prune(self):
        self.cache.store(
            "/tmp/old.py",
            self._entry("/tmp/old.py", cached_at=time.time() - 10 * 86400),
        )
        self.cache.store(
            "/tmp/new.py",
            self._entry("/tmp/new.py", cached_at=time.time()),
        )
        self.assertEqual(1, self.cache.prune(7))
        self.assertIn("/tmp/new.py", self.cache.entries)
        self.assertNotIn("/tmp/old.py", self.cache.entries)

    def test_prune_zero_removes_all(self):
        self.cache.store("/tmp/a.py", self._entry("/tmp/a.py"))
        self.cache.store("/tmp/b.py", self._entry("/tmp/b.py"))
        self.assertEqual(2, self.cache.prune(0))
        self.assertEqual({}, self.cache.entries)

    def test_export_includes_format_version(self):
        self.cache.store("/tmp/a.py", self._entry("/tmp/a.py"))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            self.cache.export(f)
            fname = f.name
        with open(fname) as f:
            data = json.load(f)
        self.assertEqual(b_cache.FORMAT_VERSION, data["format_version"])
        self.assertIn("/tmp/a.py", data["entries"])

    def test_import_merge(self):
        self.cache.store("/tmp/a.py", self._entry("/tmp/a.py"))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            b_cache.BanditCache(
                self.cache_dir, cache_key="other"
            ).export(f)
            fname = f.name
        # Build an export with a different entry.
        other = b_cache.BanditCache(
            os.path.join(self.tempdir, "other"), cache_key="other"
        )
        other.store("/tmp/b.py", self._entry("/tmp/b.py", cache_key="other"))
        other.save()
        with open(os.path.join(other.cache_dir, "cache.json")) as f:
            data = json.load(f)
        with open(fname, "w") as f:
            json.dump(data, f)

        target = b_cache.BanditCache(
            os.path.join(self.tempdir, "target"), cache_key="key1"
        )
        target.import_cache(fname)
        self.assertIn("/tmp/b.py", target.entries)

    def test_import_incompatible_ignored(self):
        export_file = os.path.join(self.tempdir, "export.json")
        with open(export_file, "w") as f:
            json.dump({"format_version": 999, "entries": {}}, f)
        target = b_cache.BanditCache(
            os.path.join(self.tempdir, "target"), cache_key="key1"
        )
        target.import_cache(export_file)
        self.assertEqual({}, target.entries)

    def test_import_malformed_ignored(self):
        export_file = os.path.join(self.tempdir, "export.json")
        with open(export_file, "w") as f:
            f.write("<<<not json>>>")
        target = b_cache.BanditCache(
            os.path.join(self.tempdir, "target"), cache_key="key1"
        )
        target.import_cache(export_file)
        self.assertEqual({}, target.entries)

    def test_stats_includes_file_size(self):
        self.cache.store("/tmp/a.py", self._entry("/tmp/a.py"))
        self.cache.save()
        stats = self.cache.stats()
        self.assertIn("cache_file_size_bytes", stats)
        self.assertGreater(stats["cache_file_size_bytes"], 0)
        self.assertEqual(1, stats["cached_files"])

    def test_size_limit(self):
        self.cache.store("/tmp/a.py", self._entry("/tmp/a.py"))
        self.cache.store("/tmp/b.py", self._entry("/tmp/b.py"))
        self.cache.size_limit = 1
        self.cache.save()
        self.assertTrue(os.path.exists(self.cache.cache_path))

    def test_clear_cache_noop_if_missing(self):
        missing = os.path.join(self.tempdir, "missing")
        b_cache.clear_cache_dir(missing)
        self.assertFalse(os.path.exists(missing))

    def test_clear_cache(self):
        self.cache.store("/tmp/a.py", self._entry("/tmp/a.py"))
        self.cache.save()
        b_cache.clear_cache_dir(self.cache_dir)
        self.assertFalse(os.path.exists(self.cache_dir))

    def test_cache_key_changes_with_parts(self):
        key1 = b_cache.cache_key_from_parts(tests="B101", skips=None)
        key2 = b_cache.cache_key_from_parts(tests="B102", skips=None)
        self.assertNotEqual(key1, key2)
EOF
cd /app && timeout 120 python -m pytest tests/unit/core/test_cache.py -q 2>&1 | tail -20