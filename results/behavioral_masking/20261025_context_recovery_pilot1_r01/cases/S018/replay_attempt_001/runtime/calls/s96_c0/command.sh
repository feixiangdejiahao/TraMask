cd /app && python - <<'EOF'
from bandit.core import nosec, manager
src = b"import subprocess\n\n# nosec-next-line\n@decorator\ndef foo():\n    subprocess.Popen('ls *', shell=True)\n"
m = manager.BanditManager(__import__('bandit.core.config', fromlist=['BanditConfig']).BanditConfig(), "file")
en = m._get_enabled_tests()
nl = nosec.build_nosec_lines(src, en)
print(nl)
EOF