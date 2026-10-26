cd /app && python3 - <<'PY'
path = 'backend/internal/bootstrap/services_bootstrap.go'
with open(path) as f:
    content = f.read()

# Add field to struct after Vulnerability
anchor = '\tVulnerability     *services.VulnerabilityService\n'
assert anchor in content
content = content.replace(anchor, anchor + '\tDriftDetection    *services.DriftDetectionService\n', 1)

# Add initialization after Vulnerability service init
init_anchor = '\tsvcs.Vulnerability = services.NewVulnerabilityService(db, svcs.Docker, svcs.Event, svcs.Settings, svcs.Notification)\n'
assert init_anchor in content
content = content.replace(init_anchor, init_anchor + '\tsvcs.DriftDetection = services.NewDriftDetectionService(db, svcs.Docker, svcs.Container, svcs.Event, svcs.Settings, svcs.Notification)\n', 1)

with open(path, 'w') as f:
    f.write(content)
print("services_bootstrap updated")
PY
grep -n "DriftDetection" backend/internal/bootstrap/services_bootstrap.go