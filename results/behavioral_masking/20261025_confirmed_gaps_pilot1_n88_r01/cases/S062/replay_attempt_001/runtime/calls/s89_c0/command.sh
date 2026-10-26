cd /app && python - <<'PY'
# Remove the invalid "open blocked" section from test_edge.py
src=open('/tmp/test_edge.py').read()
start = src.find('# Open blocked waiting for ack, remote closes -> EOFError')
end = src.find('# recvall after half-close')
if start!=-1 and end!=-1:
    src = src[:start] + src[end:]
    open('/tmp/test_edge.py','w').write(src)
    print('trimmed')
else:
    print('markers not found', start, end)
PY
timeout 40 python /tmp/test_edge.py