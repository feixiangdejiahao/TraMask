pkill -f 'go build' 2>/dev/null; sleep 1; cd /app/backend && nohup go build ./... > /tmp/build_all.log 2>&1 &
echo "started pid $!"