cd /app && python - <<'EOF'
from bandit.core import config, manager, test_set
b_conf = config.BanditConfig()
profile = {"include": {"B602", "B607"}}
m = manager.BanditManager(b_conf, "file", profile=profile)
print(sorted(m._get_enabled_tests()))
EOF