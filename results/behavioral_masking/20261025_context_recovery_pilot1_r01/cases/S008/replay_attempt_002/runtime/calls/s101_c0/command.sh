cd /app/backend && nohup go build -tags exclude_frontend ./internal/huma/handlers/ ./pkg/scheduler/ ./internal/models/ ./internal/bootstrap/ > /tmp/build4.log 2>&1 &
echo "started pid $!"