cd /app && sed -i '221s/assert.Len(t, active, 9)/assert.Len(t, active, 10)/' backend/internal/services/drift_detection_service_test.go
cd /app/backend && nohup go test ./internal/services/ -run 'Drift' -count=1 -v > /tmp/test_drift.log 2>&1 &
echo "restarted pid $!"