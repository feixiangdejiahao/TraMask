cd /app && python3 - <<'PY'
p='public/testem/testem_connection.js'
s=open(p).read()
s=s.replace("""  socket.on('stop-run', function() {
    sendMessageToParent('stop-run');
  });
""", """  socket.on('stop-run', function() {
    sendMessageToParent('stop-run');
  });
  socket.on('abort-tests', function() {
    sendMessageToParent('abort-tests');
  });
""",1)
open(p,'w').write(s)
PY
node -c public/testem/testem_connection.js && echo OK