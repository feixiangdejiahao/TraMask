cd /app/backend && nohup go build ./internal/services/ ./internal/huma/handlers/ ./pkg/scheduler/ ./internal/bootstrap/ ./internal/models/ > /tmp/build2.log 2>&1 &
echo "started pid $!"