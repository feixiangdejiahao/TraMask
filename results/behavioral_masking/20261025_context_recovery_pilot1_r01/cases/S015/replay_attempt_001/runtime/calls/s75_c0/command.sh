cd /app && rm -rf /tmp/kconfig && mkdir -p /tmp/kconfig && cat > /tmp/kconfig/bandit.yaml <<'EOF'
profiles:
  test:
    include:
      - B602
incremental_analysis:
  enabled: true
  cache_directory: /tmp/kconfig/.cache
EOF
cat > /tmp/kconfig/a.py <<'EOF'
import os
os.system("ls")
EOF
python -m bandit /tmp/kconfig/a.py -c /tmp/kconfig/bandit.yaml -f json 2>/dev/null >/tmp/kc1; echo "run1 exit=$?"; python -c "import json; print(json.load(open('/tmp/kc1'))['cache_info'])"
python -m bandit /tmp/kconfig/a.py -c /tmp/kconfig/bandit.yaml -f json 2>/dev/null >/tmp/kc2; python -c "import json; print(json.load(open('/tmp/kc2'))['cache_info'])"
# change shell config
cat > /tmp/kconfig/bandit.yaml <<'EOF'
profiles:
  test:
    include:
      - B602
shell_injection:
  shell:
    - os.system
incremental_analysis:
  enabled: true
  cache_directory: /tmp/kconfig/.cache
EOF
python -m bandit /tmp/kconfig/a.py -c /tmp/kconfig/bandit.yaml -f json 2>/dev/null >/tmp/kc3; python -c "import json; print(json.load(open('/tmp/kc3'))['cache_info'])"