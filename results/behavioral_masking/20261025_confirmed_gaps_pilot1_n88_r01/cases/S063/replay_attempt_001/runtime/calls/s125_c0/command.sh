cd /app && python - <<'PYEOF'
path = 'CHANGELOG.md'
s = open(path).read()
marker = "## 5.0.0 (`dev`)\n\n"
insert = "- Add `pwnlib.tubes.mux.TubeMultiplexer` / `MuxChannel` for multiplexing logical channels over a single tube\n- Add `Buffer.set_watermarks()` and flow-control watermarks\n- Add `tube.mux()` helper\n"
assert marker in s
s = s.replace(marker, marker + insert, 1)
open(path,'w').write(s)
print("changelog updated")
PYEOF
head -5 CHANGELOG.md