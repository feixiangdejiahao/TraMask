cd /app && node -e "
const program = require('commander');
program.version('x').option('--bail_on_test_failure [n]', 'desc', function(v){ return v; });
program.parse(['node','x','ci','--bail_on_test_failure','3']);
console.log('with val:', program.bail_on_test_failure);
const p2 = require('commander');
p2.version('x').option('--bail_on_test_failure [n]', 'desc', function(v){ return v; });
p2.parse(['node','x','ci','--bail_on_test_failure']);
console.log('bare:', p2.bail_on_test_failure);
"