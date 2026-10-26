# Copyright 2025
#
# SPDX-License-Identifier: Apache-2.0
import os

import fixtures
import testtools

from bandit.core import cache as b_cache
from bandit.core import config
from bandit.core import manager


class ManagerCacheTests(testtools.TestCase):
    def setUp(self):
        super().setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.file_a = os.path.join(self.tempdir, "a.py")
        self.file_b = os.path.join(self.tempdir, "b.py")
        self.file_c = os.path.join(self.tempdir, "c.py")
        with open(self.file_a, "w") as f:
            f.write("import b\nb.foo()\n")
        with open(self.file_b, "w") as f:
            f.write("import a\n\ndef foo():\n    return 1\n")
        with open(self.file_c, "w") as f:
            f.write("import b\nb.foo()\n")

        self.conf = config.BanditConfig()
        self.cache_dir = os.path.join(self.tempdir, ".cache")

    def _manager(self):
        mgr = manager.BanditManager(self.conf, "file")
        mgr.discover_files([self.file_a, self.file_b, self.file_c])
        return mgr

    def _cache(self):
        return b_cache.BanditCache(
            self.cache_dir,
            cache_key="key",
            expiry_days=30,
        )

    def test_unchanged_files_are_cached(self):
        mgr = self._manager()
        cache = self._cache()
        mgr.run_tests(cache=cache)
        self.assertEqual(3, mgr.cache_misses)
        self.assertEqual(0, mgr.cache_hits)

        mgr2 = self._manager()
        cache2 = self._cache()
        mgr2.run_tests(cache=cache2)
        self.assertEqual(0, mgr2.cache_misses)
        self.assertEqual(3, mgr2.cache_hits)
        self.assertEqual(0, len(mgr2.results))

    def test_dependency_change_invalidates_circular_imports(self):
        mgr = self._manager()
        mgr.run_tests(cache=self._cache())

        with open(self.file_b, "w") as f:
            f.write("import a\n\ndef foo():\n    return 2\n")

        mgr2 = self._manager()
        cache2 = self._cache()
        mgr2.run_tests(cache=cache2)
        self.assertEqual(3, mgr2.cache_misses)
        self.assertEqual(
            3, mgr2.invalidation_counts["file_changed"]
        )

    def test_force_rescan_still_stores(self):
        mgr = self._manager()
        mgr.run_tests(cache=self._cache())

        mgr2 = self._manager()
        cache2 = self._cache()
        mgr2.run_tests(cache=cache2, force_rescan=True)
        self.assertEqual(3, mgr2.cache_misses)
        self.assertEqual(0, mgr2.cache_hits)

        mgr3 = self._manager()
        cache3 = self._cache()
        mgr3.run_tests(cache=cache3)
        self.assertEqual(3, mgr3.cache_hits)

    def test_expiry_zero_expires_all(self):
        mgr = self._manager()
        mgr.run_tests(cache=self._cache())

        cache = b_cache.BanditCache(
            self.cache_dir, cache_key="key", expiry_days=0
        )
        mgr2 = self._manager()
        mgr2.run_tests(cache=cache)
        self.assertEqual(3, mgr2.cache_misses)
        self.assertEqual(3, mgr2.invalidation_counts["expired"])

    def test_cache_key_change_is_config_changed(self):
        mgr = self._manager()
        mgr.run_tests(cache=self._cache())

        cache = b_cache.BanditCache(
            self.cache_dir, cache_key="different", expiry_days=30
        )
        mgr2 = self._manager()
        mgr2.run_tests(cache=cache)
        self.assertEqual(3, mgr2.cache_misses)
        self.assertEqual(3, mgr2.invalidation_counts["config_changed"])
