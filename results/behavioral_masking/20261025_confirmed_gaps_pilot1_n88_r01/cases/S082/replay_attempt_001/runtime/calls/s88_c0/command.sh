cd /app && sed -i 's/^const ProcessTestRunner = require/const ProcessTestRunner2 = require/; s/const ProcessTestRunner = require/const ProcessTestRunner = require/' check_bail_tmp.js && python3 - <<'PY'
p='check_bail_tmp.js'
s=open(p).read()
s=s.replace("const ProcessTestRunner2 = require('./lib/runners/process_test_runner');\nconst ProcessTestRunner = require('./lib/runners/process_test_runner');","const ProcessTestRunner = require('./lib/runners/process_test_runner');")
# remove duplicate first require by replacing the line before the second usage
s=s.replace("const ProcessTestRunner = require('./lib/runners/process_test_runner');\nconst BrowserTestRunner","const BrowserTestRunner")
open(p,'w').write(s)
PY
node check_bail_tmp.js