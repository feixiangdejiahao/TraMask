cd /app && cat > check_bail_tmp3.js <<'EOF'
'use strict';
const Config = require('./lib/config');
const Reporter = require('./lib/utils/reporter');
const PassThrough = require('stream').PassThrough;
const TapReporter = require('./lib/reporters/tap_reporter');

const c = new Config('ci', {});
c.config.bail_on_test_failure = 1;
const app = { config: c, reporter: null, on(){}, emit(){}, server:{resetAbort(){}} };
const stream = new PassThrough();
const reporter = new Reporter(app, stream);
app.reporter = reporter;
reporter.reporters = [new TapReporter(false, stream, c, app)];
reporter.report('chrome', {name:'pass1', passed:true});
reporter.report('chrome', {name:'fail1', passed:false});
reporter.report('chrome', {name:'late', passed:true});
console.log('sub total before reset:', reporter.reporters[0].total);
reporter.resetBailState();
console.log('sub total after reset:', reporter.reporters[0].total);
reporter.report('chrome', {name:'post', passed:true});
reporter.finish();
console.log(stream.read().toString());
EOF
node check_bail_tmp3.js