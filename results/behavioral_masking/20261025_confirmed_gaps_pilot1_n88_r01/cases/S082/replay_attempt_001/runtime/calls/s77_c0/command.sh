cd /app && cat > public/testem/jasmine2_adapter.js <<'EOF'
/*

 jasmine2_adapter.js
 ==================

 Testem's adapter for Jasmine. It works by adding a custom reporter.

 */

/* globals emit, jasmine */
/* exported jasmine2Adapter */
'use strict';

function jasmine2Adapter() {

  var results = {
    failed: 0,
    passed: 0,
    total: 0,
    pending: 0,
    tests: []
  };
  var allTestResultsSignaled = false;

  function aborted() {
    return typeof Testem !== 'undefined' && Testem.aborted;
  }

  function signalAllTestResults() {
    if (!allTestResultsSignaled) {
      allTestResultsSignaled = true;
      emit('all-test-results');
    }
  }

  function Jasmine2AdapterReporter() {

    this.jasmineStarted = function() {
      if (!aborted()) {
        emit('tests-start');
      }
    };

    this.specStarted = function(spec) {
      if (aborted()) {
        return;
      }
      var currentTest = {
        name: spec.fullName
      };
      emit('tests-start', currentTest);
    };

    this.specDone = function(spec) {
      if (aborted()) {
        return;
      }

      var test = {
        passed: 0,
        failed: 0,
        total: 0,
        pending: 0,
        id: spec.id + 1,
        name: spec.fullName,
        items: []
      };

      var i, l, failedExpectations, item;

      if (spec.status === 'passed') {
        test.passed++;
        test.total++;
        results.passed++;
      } else if (spec.status === 'pending') {
        test.pending++;
        test.total++;
        results.pending++;
      } else {
        failedExpectations = spec.failedExpectations;
        for (i = 0, l = failedExpectations.length; i < l; i++) {
          item = failedExpectations[i];
          test.items.push({
            passed: item.passed,
            message: item.message,
            stack: item.stack || undefined
          });
        }
        test.failed++;
        results.failed++;
        test.total++;
      }

      results.total++;

      emit('test-result', test);
    };

    this.jasmineDone = function() {
      if (aborted()) {
        signalAllTestResults();
      } else {
        emit('all-test-results');
      }
    };

  }

  jasmine.getEnv().addReporter(new Jasmine2AdapterReporter());
}
EOF
node -c public/testem/jasmine2_adapter.js && echo OK