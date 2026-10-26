cd /app && python3 - <<'PY'
path = 'backend/internal/bootstrap/jobs_bootstrap.go'
with open(path) as f:
    content = f.read()

anchor = '''\tautoHealJob := pkg_scheduler.NewAutoHealJob(appServices.Docker, appServices.Settings, appServices.Event, appServices.Notification)
\tnewScheduler.RegisterJob(autoHealJob)

'''
assert anchor in content
content = content.replace(anchor, anchor + '''\tdriftDetectionJob := pkg_scheduler.NewDriftDetectionJob(appServices.DriftDetection, appServices.Settings)
\tnewScheduler.RegisterJob(driftDetectionJob)

''', 1)

with open(path, 'w') as f:
    f.write(content)
print("jobs_bootstrap updated")
PY
grep -n "DriftDetection\|driftDetection" backend/internal/bootstrap/jobs_bootstrap.go