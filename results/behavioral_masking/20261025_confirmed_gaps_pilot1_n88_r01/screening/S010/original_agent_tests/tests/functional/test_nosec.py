#
# SPDX-License-Identifier: Apache-2.0
import os

import fixtures
import testtools

from bandit.core import config as b_config
from bandit.core import manager as b_manager
from bandit.core import metrics as b_metrics
from bandit.core import test_set as b_test_set


class NosecFunctionalTests(testtools.TestCase):
    """Functional tests for nosec suppression directives."""

    def setUp(self):
        super().setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        b_conf = b_config.BanditConfig()
        path = os.path.join(os.getcwd(), "bandit", "plugins")
        b_conf._settings["plugins_dir"] = path
        self.b_mgr = b_manager.BanditManager(b_conf, "file")
        self.b_mgr.b_ts = b_test_set.BanditTestSet(config=b_conf)

    def _run(self, source, ignore_nosec=False):
        """Write source to a temp file and run bandit on it."""
        fname = os.path.join(self.tempdir, "nosec_test.py")
        with open(fname, "w") as f:
            f.write(source)
        self.b_mgr.metrics = b_metrics.Metrics()
        self.b_mgr.results = []
        self.b_mgr.scores = []
        self.b_mgr.ignore_nosec = ignore_nosec
        self.b_mgr.discover_files([fname], True)
        self.b_mgr.run_tests()
        return self.b_mgr.results

    def _findings(self, results):
        return [(r.lineno, r.test_id) for r in results]

    def test_nosec_region(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-begin\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "# nosec-end\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        self.assertNotIn((3, "B602"), self._findings(results))
        self.assertNotIn((4, "B602"), self._findings(results))
        self.assertIn((6, "B602"), self._findings(results))

    def test_nosec_region_selector(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-begin B602\n"
            "subprocess.Popen('#not_a_path', shell=True)\n"
            "# nosec-end\n"
        )
        findings = self._findings(results)
        self.assertNotIn((3, "B602"), findings)
        self.assertIn((3, "B607"), findings)

    def test_nosec_region_auto_end(self):
        results = self._run(
            "import subprocess\n"
            "def f():\n"
            "    # nosec-begin\n"
            "    subprocess.Popen('/bin/ls *', shell=True)\n"
            "    subprocess.Popen('/bin/ls *', shell=True)\n"
            "def g():\n"
            "    subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertNotIn((4, "B602"), findings)
        self.assertNotIn((5, "B602"), findings)
        self.assertIn((7, "B602"), findings)

    def test_nosec_region_unterminated(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-begin\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertNotIn((3, "B602"), findings)
        self.assertNotIn((4, "B602"), findings)

    def test_nosec_region_statement_wide(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-begin\n"
            "subprocess.Popen('/bin/ls *',\n"
            "# nosec-end\n"
            "                 shell=True)\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertNotIn((3, "B602"), findings)
        self.assertIn((6, "B602"), findings)

    def test_nosec_next_line(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-next-line\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertNotIn((3, "B602"), findings)
        self.assertIn((4, "B602"), findings)

    def test_nosec_next_line_skips_lines(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-next-line\n"
            "\n"
            "# comment only\n"
            "(\n"
            ")\n"
            "...\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertNotIn((9, "B602"), findings)

    def test_nosec_next_line_selector(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-next-line B607\n"
            "subprocess.Popen('#not_a_path', shell=True)\n"
            "subprocess.Popen('#not_a_path', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertNotIn((3, "B607"), findings)
        self.assertIn((3, "B602"), findings)
        self.assertIn((4, "B602"), findings)
        self.assertIn((4, "B607"), findings)

    def test_nosec_none_no_effect(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-begin none\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "# nosec-end\n"
            "# nosec-next-line none\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertIn((3, "B602"), findings)
        self.assertIn((6, "B602"), findings)

    def test_nosec_expression_selector(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-begin B60* & B602\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "# nosec-end\n"
            "# nosec-begin !B607\n"
            "subprocess.Popen('#not_a_path', shell=True)\n"
            "# nosec-end\n"
        )
        findings = self._findings(results)
        self.assertNotIn((3, "B602"), findings)
        self.assertIn((6, "B607"), findings)
        self.assertNotIn((6, "B602"), findings)

    def test_nosec_unmatched_end(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-end\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        self.assertIn((3, "B602"), self._findings(results))

    def test_nosec_ignore(self):
        results = self._run(
            "import subprocess\n"
            "# nosec-begin\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "# nosec-end\n"
            "# nosec-next-line\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n",
            ignore_nosec=True,
        )
        findings = self._findings(results)
        self.assertIn((3, "B602"), findings)
        self.assertIn((6, "B602"), findings)

    def test_nosec_metrics(self):
        self._run(
            "import subprocess\n"
            "# nosec-begin\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "# nosec-end\n"
            "# nosec-begin B602\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "# nosec-end\n"
            "# nosec-next-line B607\n"
            "subprocess.Popen('#not_a_path', shell=True)\n"
        )
        m = self.b_mgr.metrics.data["_totals"]
        self.assertEqual(2, m["nosec"])
        self.assertEqual(2, m["skipped_tests"])

    def test_nosec_keywords_case_insensitive(self):
        results = self._run(
            "import subprocess\n"
            "# NOSEC-BEGIN\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
            "# NOSEC-END\n"
            "# NOSEC-NEXT-LINE B602\n"
            "subprocess.Popen('/bin/ls *', shell=True)\n"
        )
        findings = self._findings(results)
        self.assertNotIn((3, "B602"), findings)
        self.assertNotIn((6, "B602"), findings)
