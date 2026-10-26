cd /app && node -e "
const program = require('commander');
program.version('x');
program.command('ci').option('--bail_on_test_failure [n]', 'desc', function(v){ return v==='true'?true:parseInt(v,10); });
program.parse(['node','x','ci','--bail_on_test_failure','3']);
console.log(program.bail_on_test_failure);
"