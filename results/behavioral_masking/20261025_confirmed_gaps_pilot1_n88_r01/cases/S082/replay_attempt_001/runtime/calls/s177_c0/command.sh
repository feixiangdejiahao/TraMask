cd /app && node -e "
const App = require('./lib/app');
const Config = require('./lib/config');
const app = new App(new Config('ci', {}), function(){});
app.runners = [];
app.abortRunners().then(() => console.log('ok no server'));
"