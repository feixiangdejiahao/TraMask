cd /app/backend && nohup go test -count=1 -run 'Drift|SettingsService_EnsureDefaultSettings' ./internal/services/ > /tmp/f_svc.log 2>&1 &
nohup go test -count=1 -run 'TestComplianceRoutes' ./internal/huma/handlers/ > /tmp/f_hand.log 2>&1 &
nohup go test -count=1 -run 'TestDriftDetectionJob' ./pkg/scheduler/ > /tmp/f_job.log 2>&1 &
echo "started"