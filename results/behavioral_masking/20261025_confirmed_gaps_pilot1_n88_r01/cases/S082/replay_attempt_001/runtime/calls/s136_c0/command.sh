cd /app && python3 - <<'PY'
p='tests/mocha_adapter_tests.js'
s=open(p).read()
insert = r'''

  describe('when aborted', function() {
    let abortedGlobals;

    beforeEach(function() {
      abortedGlobals = {};
      replaceGlobals({ Testem: { aborted: true } }, abortedGlobals);
      mochaAdapter();
    });

    afterEach(function() {
      restoreGlobals(abortedGlobals);
    });

    it('suppresses events and signals all-test-results once', function() {
      let runner = new Runner();
      runner.emit('start', {}, null);
      runner.emit('test end', { state: 'passed', title: 'x' }, null);

      let deferred = _setTimeout.lastCall.args[0];
      deferred();

      runner.emit('end', {}, null);

      expect(_emit).not.to.have.been.calledWith('tests-start');
      expect(_emit).not.to.have.been.calledWith('test-result');
      expect(_emit).to.have.been.calledWith('all-test-results');
      expect(_emit).to.have.been.calledOnce();
    });
  });
'''
s = s.rstrip()
assert s.endswith('});')
s = s[:-3] + insert + '\n});\n'
open(p,'w').write(s)
PY
npx mocha tests/mocha_adapter_tests.js 2>&1 | tail -20