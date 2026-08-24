// Smoke test: execute trends.js against real dashboard data with a stubbed DOM + Chart.
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', 'dashboard');
const history = JSON.parse(fs.readFileSync(path.join(root, 'data', 'history.json'), 'utf8'));

const elements = {};
function el(id) {
  if (!elements[id]) {
    elements[id] = {
      id,
      innerHTML: '',
      textContent: '',
      style: {},
      getContext: () => ({}),
    };
  }
  return elements[id];
}

global.document = {
  getElementById: el,
};

const chartCalls = [];
global.Chart = function (ctx, config) {
  chartCalls.push({ type: config.type, datasets: config.data.datasets.length, labels: config.data.labels?.length });
  return { destroy() {} };
};

global.fetch = async (url) => ({
  ok: true,
  json: async () => history,
});

const code = fs.readFileSync(path.join(root, 'trends.js'), 'utf8');
eval(code);

(async () => {
  await new Promise(r => setTimeout(r, 50));
  console.log('charts rendered:', chartCalls.length);
  for (const c of chartCalls) console.log(`  ${c.type}: ${c.datasets} dataset(s), ${c.labels ?? 0} labels`);
  console.log('records html length:', el('records-grid').innerHTML.length);
  console.log('board-repos rows:', (el('board-repos').innerHTML.match(/board-row/g) || []).length);
  console.log('board-owners rows:', (el('board-owners').innerHTML.match(/board-row/g) || []).length);
  console.log('spark cards:', (el('spark-grid').innerHTML.match(/spark-card/g) || []).length);
  console.log('header sub:', el('header-sub').textContent);
  console.log('pills:', el('stats-pills').innerHTML.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim());
  const rec = el('records-grid').innerHTML;
  if (/undefined|NaN/.test(rec) || /undefined|NaN/.test(el('board-repos').innerHTML)) {
    console.error('FAIL: undefined/NaN leaked into rendered HTML');
    process.exit(1);
  }
  console.log('SMOKE TEST PASS');
})().catch(e => { console.error('FAIL:', e); process.exit(1); });
