cd /app && python3 - <<'PY'
path = 'backend/internal/huma/huma.go'
with open(path) as f:
    content = f.read()
anchor = '\tVulnerability     *services.VulnerabilityService\n'
assert anchor in content
content = content.replace(anchor, anchor + '\tDriftDetection    *services.DriftDetectionService\n', 1)
with open(path, 'w') as f:
    f.write(content)
print("huma.go struct updated")
PY
grep -n "DriftDetection" backend/internal/huma/huma.go