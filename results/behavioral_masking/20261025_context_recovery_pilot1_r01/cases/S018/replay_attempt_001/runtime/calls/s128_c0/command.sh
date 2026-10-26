cd /app && python - <<'EOF'
from bandit.core import config, manager
import tempfile, os
b_conf = config.BanditConfig()
profile = {"include": {"B602", "B607"}}
m = manager.BanditManager(b_conf, "file", profile=profile)
src = b"import subprocess\n# nosec-next-line !B602\nsubprocess.Popen('ls *', shell=True)\n"
fd, path = tempfile.mkstemp(suffix='.py')
os.write(fd, src); os.close(fd)
m.discover_files([path], True)
m.run_tests()
print('metrics', m.metrics.data['_totals'])
for r in m.results:
    print(r.lineno, r.test_id)
os.unlink(path)
EOF