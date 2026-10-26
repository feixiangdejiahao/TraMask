cd /app && python3 - <<'PY'
p='tests/utils/reporter_tests.js'
s=open(p).read()
s=s.replace("""const Bluebird = require('bluebird');
const expect = require('chai').expect;
""", """const Bluebird = require('bluebird');
const log = require('npmlog');
const expect = require('chai').expect;
""",1)
open(p,'w').write(s)
PY
npx mocha tests/utils/reporter_tests.js 2>&1 | tail -20