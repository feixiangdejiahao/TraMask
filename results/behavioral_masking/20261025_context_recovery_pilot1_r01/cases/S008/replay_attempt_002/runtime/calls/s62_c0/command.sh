cd /app/backend && nohup go build ./internal/services/ > /tmp/build.log 2>&1 &
echo "started pid $!"