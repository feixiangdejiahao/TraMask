cd /app && python3 - <<'PY'
path = 'backend/internal/services/drift_detection_service_test.go'
with open(path) as f:
    content = f.read()

# Capture baseline variable
old = '''\t_, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", baselineConfigs)
\trequire.NoError(t, err)

\tlive := sampleContainerConfigs()
\tlive["web"] = models.ContainerConfig{
\t\tImage: "nginx:latest",
\t\tEnv:   []string{"B=2", "A=1"},
\t\tPorts: []string{"443/tcp", "80/tcp"},
\t}'''
new = '''\tbaseline, err := svc.CaptureBaselineFromConfigs(ctx, "env1", "b", "", "u", baselineConfigs)
\trequire.NoError(t, err)

\tlive := sampleContainerConfigs()
\tlive["web"] = models.ContainerConfig{
\t\tImage: "nginx:latest",
\t\tEnv:   []string{"B=2", "A=1"},
\t\tPorts: []string{"443/tcp", "80/tcp"},
\t}'''
assert old in content
content = content.replace(old, new, 1)

# Fix Count usage
old2 = '''\tvar records []models.DriftRecord
\trequire.NoError(t, db.WithContext(ctx).Where("baseline_id = ?", baseline.ID).Count(&records).Error)
\tassert.Empty(t, records)'''
new2 = '''\tvar count int64
\trequire.NoError(t, db.WithContext(ctx).Model(&models.DriftRecord{}).Where("baseline_id = ?", baseline.ID).Count(&count).Error)
\tassert.Zero(t, count)'''
assert old2 in content
content = content.replace(old2, new2, 1)

with open(path, 'w') as f:
    f.write(content)
print("fixed")
PY
cd /app/backend && gofmt -w internal/services/drift_detection_service_test.go
nohup go test ./internal/services/ -run 'Drift' -count=1 -v > /tmp/test_drift.log 2>&1 &
echo "restarted pid $!"