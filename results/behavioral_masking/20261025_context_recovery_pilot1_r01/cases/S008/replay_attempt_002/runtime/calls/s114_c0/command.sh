cd /app/backend && nohup go test ./internal/huma/handlers/ -run 'TestComplianceRoutes' -count=1 -v > /tmp/test_compliance.log 2>&1 &
echo "started pid $!"