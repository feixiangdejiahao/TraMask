cd /app/backend && nohup go test ./internal/services/ -run 'Drift' -count=1 -v > /tmp/test_drift.log 2>&1 &
echo "started pid $!"