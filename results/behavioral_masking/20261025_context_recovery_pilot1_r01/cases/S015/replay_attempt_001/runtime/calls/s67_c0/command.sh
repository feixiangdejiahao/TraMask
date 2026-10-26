cat > tests/functional/test_incremental.py <<'EOF'
# Copyright 2025
#
# SPDX-License-Identifier: Apache-2.0
import json
import os
import subprocess
import sys

import fixtures
import testtools


class IncrementalTests(testtools.TestCase):
    def setUp(self):
        super().setUp()
        self.workdir = self.useFixture(fixtures.TempDir()).path
        self.file_a = os.path.join(self.workdir, "a.py")
        with open(self.file_a, "w") as f:
            f.write('import os\nos.system("ls")\n')

    def _run(self, *args, cwd=None):
        cmd = [sys.executable, "-m", "bandit"] + list(args)
        proc = subprocess.run(
            cmd,
            cwd=cwd or self.workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        return proc

    def _run_json(self, *args, cwd=None):
        proc = self._run(*args, "--exit-zero", cwd=cwd)
        self.assertEqual(0, proc.returncode, proc.stderr.decode())
        data = json.loads(proc.stdout.decode())
        return data, proc

    def _cache_dir(self):
        return os.path.join(self.workdir, ".cache")

    def _incremental_json(self, *args):
        return self._run_json(
            self.file_a,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "-f",
            "json",
            *args,
        )

    def test_incremental_cached_results(self):
        data1, _ = self._incremental_json()
        self.assertEqual(1, data1["cache_info"]["cache_misses"])
        self.assertEqual(0, data1["cache_info"]["cache_hits"])

        data2, _ = self._incremental_json()
        self.assertEqual(0, data2["cache_info"]["cache_misses"])
        self.assertEqual(1, data2["cache_info"]["cache_hits"])
        self.assertEqual(len(data1["results"]), len(data2["results"]))
        self.assertEqual(data1["results"], data2["results"])

    def test_incremental_file_changed(self):
        self._incremental_json()
        with open(self.file_a, "w") as f:
            f.write('import subprocess\nsubprocess.call("ls", shell=True)\n')
        data, _ = self._incremental_json()
        self.assertEqual(1, data["cache_info"]["cache_misses"])
        self.assertEqual(
            1, data["cache_info"]["invalidation_counts"]["file_changed"]
        )

    def test_disabled_by_default(self):
        proc = self._run(self.file_a, "-f", "json")
        self.assertFalse(os.path.exists(self._cache_dir()))
        data = json.loads(proc.stdout.decode())
        self.assertEqual(0, data["cache_info"]["cache_hits"])
        self.assertEqual(0, data["cache_info"]["cache_misses"])

    def test_config_enabled(self):
        config = os.path.join(self.workdir, "bandit.yaml")
        cache_dir = os.path.join(self.workdir, "conf_cache")
        with open(config, "w") as f:
            f.write(
                "incremental_analysis:\n"
                "    enabled: true\n"
                f"    cache_directory: {cache_dir}\n"
                "    cache_expiry_days: 30\n"
            )
        data1, _ = self._run_json(self.file_a, "-c", config, "-f", "json")
        self.assertEqual(1, data1["cache_info"]["cache_misses"])
        self.assertTrue(os.path.isdir(cache_dir))
        data2, _ = self._run_json(self.file_a, "-c", config, "-f", "json")
        self.assertEqual(1, data2["cache_info"]["cache_hits"])

    def test_no_incremental_overrides_config(self):
        config = os.path.join(self.workdir, "bandit.yaml")
        cache_dir = os.path.join(self.workdir, "conf_cache")
        with open(config, "w") as f:
            f.write(
                "incremental_analysis:\n"
                "    enabled: true\n"
                f"    cache_directory: {cache_dir}\n"
            )
        proc = self._run(
            self.file_a, "-c", config, "--no-incremental", "-f", "json"
        )
        self.assertFalse(os.path.exists(cache_dir))
        data = json.loads(proc.stdout.decode())
        self.assertEqual(0, data["cache_info"]["cache_hits"])
        self.assertEqual(0, data["cache_info"]["cache_misses"])

    def test_cache_expiry_zero(self):
        config = os.path.join(self.workdir, "bandit.yaml")
        cache_dir = os.path.join(self.workdir, "conf_cache")
        with open(config, "w") as f:
            f.write(
                "incremental_analysis:\n"
                "    enabled: true\n"
                f"    cache_directory: {cache_dir}\n"
                "    cache_expiry_days: 0\n"
            )
        self._run_json(self.file_a, "-c", config, "-f", "json")
        data, _ = self._run_json(self.file_a, "-c", config, "-f", "json")
        self.assertEqual(1, data["cache_info"]["cache_misses"])
        self.assertEqual(
            1, data["cache_info"]["invalidation_counts"]["expired"]
        )

    def test_clear_cache_noop_if_missing(self):
        missing = os.path.join(self.workdir, "does-not-exist")
        proc = self._run("--clear-cache", "--cache-dir", missing)
        self.assertEqual(0, proc.returncode)
        self.assertFalse(os.path.exists(missing))

    def test_clear_cache(self):
        self._incremental_json()
        proc = self._run("--clear-cache", "--cache-dir", self._cache_dir())
        self.assertEqual(0, proc.returncode)
        self.assertFalse(os.path.exists(self._cache_dir()))

    def test_cache_summary(self):
        self._incremental_json()
        proc = self._run("--cache-summary", "--cache-dir", self._cache_dir())
        self.assertEqual(0, proc.returncode)
        self.assertEqual("Cached files: 1\n", proc.stdout.decode())

    def test_force_rescan_requires_incremental(self):
        proc = self._run(
            self.file_a,
            "--force-rescan",
            "--cache-dir",
            self._cache_dir(),
            "-f",
            "json",
        )
        self.assertIn("--force-rescan", proc.stderr.decode())
        self.assertFalse(os.path.exists(self._cache_dir()))

    def test_force_rescan_with_incremental(self):
        self._incremental_json()
        data, _ = self._run_json(
            self.file_a,
            "--incremental",
            "--force-rescan",
            "--cache-dir",
            self._cache_dir(),
            "-f",
            "json",
        )
        self.assertEqual(1, data["cache_info"]["cache_misses"])
        data2, _ = self._incremental_json()
        self.assertEqual(1, data2["cache_info"]["cache_hits"])

    def test_warm_cache(self):
        proc = self._run(
            self.file_a,
            "--warm-cache",
            "--cache-dir",
            self._cache_dir(),
            "-f",
            "json",
        )
        self.assertEqual(0, proc.returncode)
        self.assertEqual(b"", proc.stdout)
        summary = self._run(
            "--cache-summary", "--cache-dir", self._cache_dir()
        )
        self.assertEqual("Cached files: 1\n", summary.stdout.decode())

    def test_export_import_cache(self):
        self._incremental_json()
        export_file = os.path.join(self.workdir, "export.json")
        proc = self._run(
            "--export-cache", export_file, "--cache-dir", self._cache_dir()
        )
        self.assertEqual(0, proc.returncode)
        with open(export_file) as f:
            exported = json.load(f)
        self.assertIn("format_version", exported)
        self.assertIn(self.file_a, exported["entries"])

        new_cache = os.path.join(self.workdir, "new_cache")
        proc = self._run("--import-cache", export_file, "--cache-dir", new_cache)
        self.assertEqual(0, proc.returncode)
        summary = self._run("--cache-summary", "--cache-dir", new_cache)
        self.assertEqual("Cached files: 1\n", summary.stdout.decode())

    def test_import_incompatible_format(self):
        bad_file = os.path.join(self.workdir, "bad.json")
        with open(bad_file, "w") as f:
            json.dump({"format_version": 999, "entries": {}}, f)
        new_cache = os.path.join(self.workdir, "new_cache")
        proc = self._run("--import-cache", bad_file, "--cache-dir", new_cache)
        self.assertEqual(0, proc.returncode)
        summary = self._run("--cache-summary", "--cache-dir", new_cache)
        self.assertEqual("Cached files: 0\n", summary.stdout.decode())

    def test_import_malformed(self):
        bad_file = os.path.join(self.workdir, "bad.json")
        with open(bad_file, "w") as f:
            f.write("not json{")
        new_cache = os.path.join(self.workdir, "new_cache")
        proc = self._run("--import-cache", bad_file, "--cache-dir", new_cache)
        self.assertEqual(0, proc.returncode)

    def test_list_cached_files(self):
        self._incremental_json()
        proc = self._run(
            "--list-cached-files", "--cache-dir", self._cache_dir()
        )
        self.assertEqual(0, proc.returncode)
        expected = os.path.abspath(self.file_a) + "\n"
        self.assertEqual(expected, proc.stdout.decode())

    def test_prune_cache(self):
        self._incremental_json()
        proc = self._run(
            "--prune-cache", "0", "--cache-dir", self._cache_dir()
        )
        self.assertEqual(0, proc.returncode)
        summary = self._run(
            "--cache-summary", "--cache-dir", self._cache_dir()
        )
        self.assertEqual("Cached files: 0\n", summary.stdout.decode())

    def test_cache_stats_includes_size(self):
        self._incremental_json()
        proc = self._run("--cache-stats", "--cache-dir", self._cache_dir())
        self.assertEqual(0, proc.returncode)
        output = proc.stdout.decode()
        self.assertIn("cache_file_size_bytes:", output)
        self.assertIn("cached_files: 1", output)

    def test_circular_imports_no_infinite_loop(self):
        file_b = os.path.join(self.workdir, "b.py")
        file_c = os.path.join(self.workdir, "c.py")
        with open(file_b, "w") as f:
            f.write("import a\n\ndef foo():\n    return 1\n")
        with open(file_c, "w") as f:
            f.write("import b\nb.foo()\n")
        with open(self.file_a, "w") as f:
            f.write("import b\nb.foo()\n")

        data1, _ = self._run_json(
            self.workdir,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "-r",
            "-f",
            "json",
        )
        self.assertEqual(3, data1["cache_info"]["cache_misses"])
        data2, _ = self._run_json(
            self.workdir,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "-r",
            "-f",
            "json",
        )
        self.assertEqual(3, data2["cache_info"]["cache_hits"])

        with open(file_b, "w") as f:
            f.write("import a\n\ndef foo():\n    return 2\n")
        data3, _ = self._run_json(
            self.workdir,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "-r",
            "-f",
            "json",
        )
        self.assertEqual(3, data3["cache_info"]["cache_misses"])
        self.assertEqual(
            3, data3["cache_info"]["invalidation_counts"]["file_changed"]
        )

    def test_cache_key_includes_analysis_options(self):
        self._run_json(
            self.file_a,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "-l",
            "-f",
            "json",
        )
        data, _ = self._run_json(
            self.file_a,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "-ll",
            "-f",
            "json",
        )
        self.assertEqual(1, data["cache_info"]["cache_misses"])
        self.assertEqual(
            1, data["cache_info"]["invalidation_counts"]["config_changed"]
        )

    def test_corrupted_cache_discarded(self):
        self._incremental_json()
        cache_file = os.path.join(self._cache_dir(), "cache.json")
        with open(cache_file, "w") as f:
            f.write("corrupted{")
        data, _ = self._incremental_json()
        self.assertEqual(1, data["cache_info"]["cache_misses"])
        self.assertEqual(
            1, data["cache_info"]["invalidation_counts"]["not_cached"]
        )

    def test_json_cache_info_section(self):
        data, _ = self._incremental_json()
        self.assertIn("cache_info", data)
        self.assertIn("total_files", data["cache_info"])
        self.assertIn("cache_hits", data["cache_info"])
        self.assertIn("cache_misses", data["cache_info"])
        self.assertIn("invalidation_counts", data["cache_info"])
        for key in ("file_changed", "config_changed", "expired", "not_cached"):
            self.assertIn(key, data["cache_info"]["invalidation_counts"])

    def test_metrics_include_cache_hits_misses(self):
        data, _ = self._incremental_json()
        self.assertIn("cache_hits", data["metrics"]["_totals"])
        self.assertIn("cache_misses", data["metrics"]["_totals"])

    def test_verbose_cache_output(self):
        self._incremental_json()
        proc = self._run(
            self.file_a,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "--verbose",
            "-f",
            "txt",
        )
        output = proc.stdout.decode()
        self.assertIn("Files cached: 1, Files scanned: 0", output)

    def test_cache_size_limit(self):
        self._run_json(
            self.file_a,
            "--incremental",
            "--cache-dir",
            self._cache_dir(),
            "--cache-size-limit",
            "1",
            "-f",
            "json",
        )
        proc = self._run("--cache-stats", "--cache-dir", self._cache_dir())
        output = proc.stdout.decode()
        self.assertIn("cached_files: 0", output)
EOF
cd /app && python - <<'PY'
for fn in ['tests/functional/test_incremental.py']:
    bad = []
    for i, line in enumerate(open(fn), 1):
        if len(line.rstrip('\n')) > 79:
            bad.append((i, len(line.rstrip())))
    print(fn, bad)
PY