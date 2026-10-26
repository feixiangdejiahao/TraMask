cd /app && cat > lib/reporters/teamcity_reporter.js <<'EOF'
'use strict';

function namify(prefix, result) {
  let line = (prefix ? (prefix + ' - ') : '') +
    result.name.trim();

  return escape(line);
}

/**
 * Borrowed from https://github.com/travisjeffery/mocha-teamcity-reporter
 * Escape the given `str`.
 */

function escape(str) {
  if (!str) {
    return '';
  }
  return str
    .toString()
    .replace(/\|/g, '||')
    .replace(/\n/g, '|n')
    .replace(/\r/g, '|r')
    .replace(/\[/g, '|[')
    .replace(/\]/g, '|]')
    .replace(/\u0085/g, '|x')
    .replace(/\u2028/g, '|l')
    .replace(/\u2029/g, '|p')
    .replace(/'/g, '|\'');
}

function teamcityLine(type, options) {
  const attributes = Object.keys(options)
    .map(attributeName => `${attributeName}='${options[attributeName]}'`)
    .join(' ');

  return `##teamcity[${type} ${attributes}]\n`;
}

function runDurationAttribute(result) {
  return typeof result.runDuration === 'number' ? {duration: result.runDuration} : undefined;
}

module.exports = class TeamcityReporter {
  constructor(silent, out, config, app) {
    this.out = out || process.stdout;
    this.silent = silent;
    this.app = app;
    this.stoppedOnError = null;
    this.id = 1;
    this.total = 0;
    this.pass = 0;
    this.skipped = 0;
    this.startTime = new Date();
    this.endTime = null;
  }

  report(prefix, data) {
    const name = namify(prefix, data);
    this.out.write(teamcityLine('testStarted', {name}));
    this._display(prefix, data);
    this.out.write(teamcityLine('testFinished', Object.assign(
      {name},
      runDurationAttribute(data)
    )));
    this.total++;
    if (data.skipped) {
      this.skipped++;
    } else if (data.passed) {
      this.pass++;
    }
  }

  reset() {
    this.stoppedOnError = null;
    this.id = 1;
    this.total = 0;
    this.pass = 0;
    this.skipped = 0;
    this.startTime = new Date();
    this.endTime = null;
  }

  finish() {
    if (this.silent) {
      return;
    }
    this.endTime = new Date();
    this.out.write('\n\n');
    this.displayBail();
    this.out.write(teamcityLine('testSuiteFinished', {
      name: 'testem.suite',
      duration: Math.round((this.endTime - this.startTime)),
    }));
    this.out.write('\n\n');
  }

  displayBail() {
    let app = this.app;
    if (!app || !app.reporter || !app.reporter.hasBailed()) {
      return;
    }

    let report = app.reporter.getBailReport();
    let bailReason = app.reporter.bailReason;
    let failures = app.reporter.failures;

    this.out.write(teamcityLine('message', {
      text: `Bail out! ${bailReason} (${failures} failures)`,
      status: 'ERROR'
    }));
    this.out.write(teamcityLine('buildStatisticValue', {
      key: 'bailedTests',
      value: failures
    }));
    this.out.write(teamcityLine('buildStatisticValue', {
      key: 'testsBeforeBail',
      value: report.testsRanBeforeBail
    }));
    this.out.write(teamcityLine('buildStatisticValue', {
      key: 'suppressedAfterBail',
      value: app.reporter.suppressedAfterBail
    }));
    this.out.write(teamcityLine('buildProblem', {
      description: `Bail out! ${bailReason}`
    }));
  }

  _display(prefix, result) {
    if (this.silent) {
      return;
    }
    const name = namify(prefix, result);

    if (result.skipped) {
      this.out.write(teamcityLine('testIgnored', {
        name,
        message: 'pending',
      }));
    } else if (!result.passed) {
      const hasError = result.error;
      const attributes = {name};

      const message = (hasError && result.error.message) || '';
      const stack = (hasError && result.error.stack) || '';

      attributes.message = escape(message);
      attributes.details = escape(stack);

      if (
        hasError &&
        Object.prototype.hasOwnProperty.call(result.error, 'expected') &&
        Object.prototype.hasOwnProperty.call(result.error, 'actual')
      ) {
        attributes.type = 'comparisonFailure';
        attributes.expected = (result.error.negative ? 'NOT ' : '') + escape(result.error.expected);
        attributes.actual = escape(result.error.actual);
      }

      this.out.write(teamcityLine('testFailed', attributes));
    }
  }
};

module.exports.teamcityLine = teamcityLine;
EOF
node -c lib/reporters/teamcity_reporter.js && echo OK