const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const api = require('../index-memberships.js');
const data = JSON.parse(fs.readFileSync(require.resolve('../data/index_memberships.json')));
const index = api.create(data);
test('all official codes resolve, including alphanumeric codes and overlapping tags', () => {
  for (const [code, tags] of Object.entries(data.securities)) assert.deepEqual(new Set(index.memberships(code)), new Set(tags));
  assert.deepEqual(index.memberships(' 1301.t '), ['topix', 'transition']);
  assert.ok(index.memberships('141a').includes('topix_new'));
  assert.ok(index.memberships(7203).includes('nikkei225'));
  assert.deepEqual(index.memberships('141A0'), []);
});
test('filter intersects supplied ranking and keeps its order, rank and objects', () => {
  const rows = [{code:'590A', rank:4}, {code:'0000', name:'極洋',rank:5}, {code:'1301',rank:22}];
  const filtered = index.filter(rows, 'transition');
  assert.deepEqual(filtered.map(s=>s.rank), [4,22]);
  assert.equal(filtered[0], rows[0]);
  assert.equal(rows.length, 3);
  assert.deepEqual(index.filter(rows, 'all'), rows);
  assert.deepEqual(index.filter(rows, 'nikkei225'), []);
  assert.deepEqual(index.filter(rows, 'bogus'), []);
});
test('reusable selector for future event datasets', () => {
  assert.equal(index.filter([{securityCode:'1301.T'}], 'transition', row=>row.securityCode).length, 1);
});
test('rejects missing data and bad groups instead of silently producing zero matches', () => {
  for (const broken of [null, {}, {...data,securities:{}}, {...data,securities:{...data.securities,'0000':['wrong']}}]) assert.throws(()=>api.create(broken));
});
