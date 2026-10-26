cd /app && node -e "
const program = require('commander');
program.version('x');
function parseBailOnTestFailure(value) {
  if (value === true || value === 'true') return true;
  if (value === 'false') return false;
  let parsed = parseInt(value, 10);
  if (!isNaN(parsed)) return parsed;
  return value;
}
program.command('ci').option('--bail_on_test_failure [n]', 'desc', parseBailOnTestFailure);
let env;
program.commands[0].action(function(e){ env=e; });
program.parse(['node','x','ci','--bail_on_test_failure']);
console.log('bare:', env.bail_on_test_failure);
const p2 = require('commander');
p2.version('x');
p2.command('ci').option('--bail_on_test_failure [n]', 'desc', parseBailOnTestFailure);
let env2;
p2.commands[0].action(function(e){ env2=e; });
p2.parse(['node','x','ci','--bail_on_test_failure','2']);
console.log('with 2:', env2.bail_on_test_failure);
const p3 = require('commander');
p3.version('x');
p3.command('ci').option('--bail_on_test_failure [n]', 'desc', parseBailOnTestFailure);
let env3;
p3.commands[0].action(function(e){ env3=e; });
p3.parse(['node','x','ci','--bail_on_test_failure','true']);
console.log('with true:', env3.bail_on_test_failure);
"