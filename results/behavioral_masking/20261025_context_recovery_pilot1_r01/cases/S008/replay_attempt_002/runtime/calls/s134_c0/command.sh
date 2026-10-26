cd /app/backend && nohup go test ./internal/models/ -count=1 > /tmp/test_models.log 2>&1 &
echo "models test started pid $!"