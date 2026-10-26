cd /app && python3 - <<'PY'
p='tests/client_tests.js'
s=open(p).read()
insert = r'''

  it('handleAbortTests sets aborted and blocks further emitMessage', function() {
    Testem.aborted = false;
    Testem._isIframeReady = true;
    let messages = [];
    Testem.iframe = {
      contentWindow: {
        postMessage: function() {}
      }
    };
    Testem.emitMessageToIframe = function(message) {
      messages.push(message.emitArgs[0]);
    };
    let abortedEvents = 0;
    Testem.on('abort-tests', function() {
      abortedEvents++;
    });

    Testem.handleAbortTests();

    expect(Testem.aborted).to.be.true();
    expect(abortedEvents).to.equal(1);
    expect(messages).to.deep.equal(['after-tests-complete']);

    Testem.emitMessage('test-result', { name: 'late' });
    expect(messages).to.deep.equal(['after-tests-complete']);
  });
'''
s = s.rstrip()
assert s.endswith('});')
s = s[:-3] + insert + '\n});\n'
open(p,'w').write(s)
PY
npx mocha tests/client_tests.js 2>&1 | tail -15