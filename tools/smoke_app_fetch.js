import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.argv[2] || 'https://matthewww.github.io/github-trending/';
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const elements = {};
function makeEl(id) {
  return {
    id,
    innerHTML: '',
    textContent: '',
    value: '',
    options: [],
    selectedIndex: -1,
    style: {},
    dataset: {},
    classList: { add() {}, remove() {} },
    addEventListener() {},
    getContext: () => ({}),
  };
}
const pickerEl = makeEl('date-picker');
Object.defineProperty(pickerEl, 'innerHTML', {
  get() { return this._html || ''; },
  set(v) {
    this._html = v;
    this.options = [...String(v).matchAll(/value="([^"]*)"/g)].map(m => ({ value: m[1] }));
  },
});

global.document = {
  getElementById(id) {
    if (id === 'date-picker') return pickerEl;
    if (!elements[id]) elements[id] = makeEl(id);
    return elements[id];
  },
  querySelectorAll: () => [],
  querySelector: () => null,
};
global.window = global;

const realFetch = global.fetch;
global.fetch = async (url) => realFetch(url.startsWith('http') ? url : new URL(url, BASE));

const src = fs.readFileSync(path.join(__dirname, '..', 'dashboard', 'app.js'), 'utf8');
try {
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));
} catch (e) {
  console.error('APP THREW:', e.message);
  process.exit(1);
}
await new Promise(r => setTimeout(r, 4000));

console.log('picker options:', pickerEl.options.length);
console.log('first options:', pickerEl.options.slice(0, 3).map(o => o.value));
console.log('stats pills len:', (elements['stats-pills']?.innerHTML || '').length);
console.log('repo grid len:', (elements['repo-grid']?.innerHTML || '').length);
