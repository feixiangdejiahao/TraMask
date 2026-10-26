cd /app && python3 - <<'PY'
path = 'backend/internal/services/drift_detection_service_test.go'
with open(path) as f:
    content = f.read()

content = content.replace(
    '\tassert.Equal(t, 3, snapshot.HighDrifts)   // env, network, config(ports)',
    '\tassert.Equal(t, 4, snapshot.HighDrifts)   // env, network, config(ports), config(volumes)'
)
content = content.replace(
    '\trequire.Len(t, records, 9)',
    '\trequire.Len(t, records, 10)'
)
with open(path, 'w') as f:
    f.write(content)
print("fixed")
PY
cd /app/backend && gofmt -w internal/services/drift_detection_service_test.go
nohup go test ./internal/services/ -run 'Drift' -count=1 -v > /tmp/test_drift.log 2>&1 &
echo "restarted pid $!"