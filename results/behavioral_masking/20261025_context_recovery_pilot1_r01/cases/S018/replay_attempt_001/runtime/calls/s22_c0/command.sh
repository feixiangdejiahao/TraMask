cd /app && python - <<'EOF'
from bandit.core import extension_loader
from bandit.core import test_set
m = extension_loader.MANAGER
print('plugins_by_id count', len(m.plugins_by_id))
print('blacklist ids', list(m.blacklist_by_id.keys())[:5])
# load a test set with default config
from bandit.core import config
cfg = config.BanditConfig()
ts = test_set.BanditTestSet(cfg)
ids = sorted(p.plugin._test_id for p in ts.plugins)
print('testset plugin ids count', len(ids))
print(ids[:20])
print('B001 in', 'B001' in ids)
EOF