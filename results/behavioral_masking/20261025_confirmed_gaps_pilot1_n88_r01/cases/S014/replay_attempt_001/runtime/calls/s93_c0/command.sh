cd /app && cat > /tmp/debug-async.mjs <<'EOF'
import { AutocompletePrompt } from '/app/packages/core/dist/index.mjs';
import { Readable, Writable } from 'node:stream';

class MockWritable extends Writable { _write(c,e,cb){ this.buffer.push(c.toString()); cb(); } }
class MockReadable extends Readable { _read(){} }

const input = new MockReadable();
const output = new MockWritable();
output.buffer = [];
let calls = 0;
const resolver = async (search) => {
  calls++;
  if (calls <= 1) throw new Error('boom');
  return search ? [{ value: search, label: search }] : [];
};
const instance = new AutocompletePrompt({ input, output, render: () => 'foo', options: resolver, debounceMs: 10 });
instance.prompt();
await Promise.resolve();
console.log('after init loadError:', instance.loadError, 'userInput:', instance.userInput);
input.emit('keypress', 'a', { name: 'a' });
console.log('after keypress loadError:', instance.loadError, 'userInput:', instance.userInput);
await new Promise(r => setTimeout(r, 30));
console.log('after wait loadError:', instance.loadError, 'userInput:', instance.userInput, 'filtered:', JSON.stringify(instance.filteredOptions));
EOF
node /tmp/debug-async.mjs