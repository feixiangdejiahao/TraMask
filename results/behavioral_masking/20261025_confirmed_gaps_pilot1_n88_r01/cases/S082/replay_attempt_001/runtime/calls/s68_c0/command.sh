cd /app && python3 - <<'PY'
p='lib/server/index.js'
s=open(p).read()

# add abortBroadcast state in constructor
s=s.replace("""    this.sockets = {};
    this.nextSocketId = 0;
""", """    this.sockets = {};
    this.nextSocketId = 0;
    this.abortBroadcast = false;
""",1)

# add methods before stop
s=s.replace("""  stop(callback) {
    if (this.server && !this.stopped) {
""", """  broadcastAbort() {
    if (this.abortBroadcast) {
      return;
    }
    this.abortBroadcast = true;

    if (this.io) {
      this.io.emit('abort-tests');
    }
  }

  resetAbort() {
    this.abortBroadcast = false;
  }

  stop(callback) {
    if (this.server && !this.stopped) {
""",1)

open(p,'w').write(s)
PY
node -c lib/server/index.js && echo OK