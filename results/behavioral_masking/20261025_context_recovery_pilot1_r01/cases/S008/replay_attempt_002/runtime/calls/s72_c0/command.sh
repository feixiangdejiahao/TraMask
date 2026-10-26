cd /app && python3 - <<'PY'
import re
path = 'backend/internal/models/settings.go'
with open(path) as f:
    content = f.read()

# Insert after TrivyIgnore line
anchor = '\tTrivyIgnore                     SettingVariable `key:"trivyIgnore" meta:"label=.trivyignore;type=textarea;keywords=trivy,ignore,ignorefile,vulnerabilities,exceptions,exclusions;category=security;description=Trivy ignore file content - one vulnerability ID per line"`\n'
insert = '''\tDriftDetectionEnabled             SettingVariable `key:"driftDetectionEnabled" meta:"label=Drift Detection;type=boolean;keywords=drift,detection,compliance,baseline,config,change,security;category=security;description=Enable scheduled detection of container configuration drift against captured baselines"`\n\tDriftDetectionInterval            SettingVariable `key:"driftDetectionInterval" meta:"label=Drift Detection Interval;type=cron;keywords=drift,detection,compliance,baseline,interval,schedule,frequency,security;category=security;description=How often to run scheduled drift detection (cron expression)"`\n'''
assert anchor in content, "anchor not found"
content = content.replace(anchor, anchor + insert, 1)
with open(path, 'w') as f:
    f.write(content)
print("models settings updated")
PY
sed -n '104,112p' backend/internal/models/settings.go