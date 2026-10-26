cd /app && node -e "
const Config = require('./lib/config');
const program = require('commander');
program.version('x');
program.command('ci').option('--bail_on_test_failure [n]', 'desc', function(v){ return v==='true'?true:parseInt(v,10); });
let env;
program.commands[0].action(function(e){ env=e; });
program.parse(['node','x','ci','--bail_on_test_failure','3']);
console.log('env.bail_on_test_failure:', env && env.bail_on_test_failure);
"