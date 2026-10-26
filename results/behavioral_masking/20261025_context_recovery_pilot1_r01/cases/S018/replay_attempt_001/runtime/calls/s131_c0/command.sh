cd /app && python - <<'EOF'
from bandit.core import config, manager, nosec
import tempfile, os
b_conf = config.BanditConfig()
profile = {"include": {"B602", "B607"}}
m = manager.BanditManager(b_conf, "file", profile=profile)
src = b"import subprocess\n# nosec-next-line B6*\nsubprocess.Popen('ls *', shell=True)\n"
fd, path = tempfile.mkstemp(suffix='.py')
os.write(fd, src); os.close(fd)
m.discover_files([path], True); m.run_tests()
print('metrics', m.metrics.data['_totals'])
print('results', [(r.lineno, r.test_id) for r in m.results])
os.unlink(path)
EOF