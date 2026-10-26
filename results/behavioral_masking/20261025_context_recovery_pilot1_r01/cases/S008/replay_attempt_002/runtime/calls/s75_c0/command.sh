cd /app && python3 - <<'PY'
path = 'types/settings/settings.go'
with open(path) as f:
    content = f.read()
anchor = '''\t// VulnerabilityScanInterval is the cron expression for scheduled vulnerability scans.\n\t//\n\t// Required: false\n\tVulnerabilityScanInterval *string `json:"vulnerabilityScanInterval,omitempty"`\n'''
insert = '''\t// VulnerabilityScanInterval is the cron expression for scheduled vulnerability scans.\n\t//\n\t// Required: false\n\tVulnerabilityScanInterval *string `json:"vulnerabilityScanInterval,omitempty"`\n\n\t// DriftDetectionEnabled indicates if scheduled drift detection is enabled.\n\t//\n\t// Required: false\n\tDriftDetectionEnabled *string `json:"driftDetectionEnabled,omitempty"`\n\n\t// DriftDetectionInterval is the cron expression for scheduled drift detection.\n\t//\n\t// Required: false\n\tDriftDetectionInterval *string `json:"driftDetectionInterval,omitempty"`\n'''
assert anchor in content
content = content.replace(anchor, insert, 1)
with open(path, 'w') as f:
    f.write(content)
print("types settings updated")
PY
cd /app/types && gofmt -w settings/settings.go && cd /app && grep -n "DriftDetection" types/settings/settings.go