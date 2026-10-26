    def test_nosec_directives(self):
        """Test `# nosec-begin`, `# nosec-end` and `# nosec-next-line`."""
        expect = {
            "SEVERITY": {"UNDEFINED": 0, "LOW": 5, "MEDIUM": 0, "HIGH": 0},
            "CONFIDENCE": {"UNDEFINED": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 5},
        }
        expect_stats = {
            "nosec": 6,
            "skipped_tests": 2,
        }
        self.check_example("nosec-directives.py", expect)
        self.check_metrics("nosec-directives.py", expect_stats)

