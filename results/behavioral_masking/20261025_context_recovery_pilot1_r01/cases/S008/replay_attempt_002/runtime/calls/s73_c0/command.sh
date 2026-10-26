cd /app && python3 - <<'PY'
path = 'backend/internal/services/settings_service.go'
with open(path) as f:
    content = f.read()
anchor = '\t\tVulnerabilityScanEnabled:        models.SettingVariable{Value: "false"},\n'
insert = '''\t\tVulnerabilityScanEnabled:        models.SettingVariable{Value: "false"},\n\t\tDriftDetectionEnabled:           models.SettingVariable{Value: "true"},\n\t\tDriftDetectionInterval:          models.SettingVariable{Value: "0 0 * * * *"},\n'''
assert anchor in content
content = content.replace(anchor, insert, 1)
with open(path, 'w') as f:
    f.write(content)
print("defaults updated")
PY
grep -n "DriftDetection" backend/internal/services/settings_service.go