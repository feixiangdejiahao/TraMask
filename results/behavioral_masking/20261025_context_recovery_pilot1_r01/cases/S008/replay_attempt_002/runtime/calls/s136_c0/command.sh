cd /app/backend && nohup go build -tags exclude_frontend -o /tmp/arcane_test ./cmd/ > /tmp/build_main.log 2>&1 &
echo "started pid $!"