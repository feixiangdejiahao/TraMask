cd /app && python - <<'EOF'
from bandit.core import config, manager
m = manager.BanditManager(config.BanditConfig(), "file")
tests = m._get_enabled_tests()
print(len(tests))
print('B301' in tests, 'B404' in tests, 'B602' in tests, 'B001' in tests)
print(sorted(t for t in tests if t.startswith('B3')))
EOF