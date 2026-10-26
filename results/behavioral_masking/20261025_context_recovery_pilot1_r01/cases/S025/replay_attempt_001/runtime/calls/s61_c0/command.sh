cat > /tmp/async_repro.mjs <<'EOF'
import { Readable, Writable } from 'node:stream';
import AutocompletePrompt from '/app/packages/core/dist/index.mjs';

class MockWritable extends Writable {
  buffer = [];
  isTTY = false;
  columns = 80;
  rows = 20;
  _write(chunk, enc, cb) { this.buffer.push(chunk.toString()); cb(); }
}
class MockReadable extends Readable {
  _buffer = [];
  _read() { if (this._buffer === null) { this.push(null); return; } for (const v of this._buffer) this.push(v); this._buffer = []; }
  pushValue(v) { this._buffer?.push(v); }
  close() { this._buffer = null; }
}

const input = new MockReadable();
const output = new MockWritable();
let calls = 0;
const resolver = async (search, { signal }) => {
  calls++;
  return [{ value: 'a', label: `A ${search}` }, { value: 'b', label: 'B' }];
};

const p = new AutocompletePrompt({
  input, output,
  render: () => `loading=${this?.loading ?? '?'}`,
  options: resolver,
});
console.log('after construct loading:', p.loading, 'filtered:', p.filteredOptions.length, 'calls:', calls);
const pr = p.prompt();
console.log('after prompt loading:', p.loading, 'state:', p.state);
await new Promise(r => setTimeout(r, 50));
console.log('after resolve loading:', p.loading, 'filtered:', p.filteredOptions.length, 'options:', p.options.map(o=>o.value), 'calls:', calls);
input.emit('keypress', 'x', { name: 'x' });
console.log('after type loading:', p.loading, 'filtered:', p.filteredOptions.length);
await new Promise(r => setTimeout(r, 300));
console.log('after debounce loading:', p.loading, 'filtered:', p.filteredOptions.length, 'calls:', calls);
process.exit(0);
EOF
node /tmp/async_repro.mjs