cd /app/backend && nohup go test ./pkg/scheduler/ -run 'TestDriftDetectionJob' -count=1 -v > /tmp/test_job.log 2>&1 &
echo "started pid $!"