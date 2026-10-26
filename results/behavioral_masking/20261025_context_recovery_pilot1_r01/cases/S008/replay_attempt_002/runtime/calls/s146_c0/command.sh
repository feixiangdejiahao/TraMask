cd /app/backend && nohup go test -count=1 -run 'TestComplianceRoutes' ./internal/huma/handlers/ > /tmp/f_hand.log 2>&1 &
cd /app/backend && nohup go test -count=1 -run 'TestDriftDetectionJob' ./pkg/scheduler/ > /tmp/f_job.log 2>&1 &
echo "restarted correctly"