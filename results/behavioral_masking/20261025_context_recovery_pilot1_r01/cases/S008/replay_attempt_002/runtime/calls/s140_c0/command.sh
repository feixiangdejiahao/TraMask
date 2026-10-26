cd /app && python3 - <<'PY'
path = 'backend/internal/services/drift_detection_service.go'
with open(path) as f:
    content = f.read()
old = '''\tif s.dockerService == nil || s.containerService == nil {
\t\treturn nil
\t}
\tif !s.IsEnabled(ctx) {
\t\treturn nil
\t}

\tvar envs []models.Environment'''
new = '''\tif s.dockerService == nil || s.containerService == nil {
\t\treturn nil
\t}
\tif !s.IsEnabled(ctx) {
\t\treturn nil
\t}
\tif s.db == nil {
\t\treturn nil
\t}

\tvar envs []models.Environment'''
assert old in content
content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print("added nil db guard")
PY
cd /app/backend && gofmt -w internal/services/drift_detection_service.go && echo OK