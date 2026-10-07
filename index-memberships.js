/* Code-keyed classification, independent of quote collection and ranking order. */
(function (root) {
  'use strict';
  const labels = Object.freeze({topix: 'TOPIX', topix_new: 'TOPIX新規', transition: '移行措置', nikkei225: '日経225'});
  const filters = Object.freeze(['all', 'transition', 'topix_new', 'topix', 'nikkei225']);
  const normalizeCode = value => {
    const code = String(value ?? '').trim().toUpperCase().replace(/\.T$/, '');
    return /^[0-9][0-9A-Z]{3}$/.test(code) ? code : '';
  };
  function create(data) {
    if (data?.schema_version !== 1 || !data.version || !data.basis_note || !data.securities || !data.groups) throw new Error('Invalid index data');
    const codes = new Map(), counts = Object.fromEntries(Object.keys(labels).map(key => [key, 0]));
    for (const [code, tags] of Object.entries(data.securities)) {
      if (normalizeCode(code) !== code || !Array.isArray(tags) || !tags.length || new Set(tags).size !== tags.length || tags.some(key => !Object.hasOwn(labels, key))) throw new Error('Invalid index membership: ' + code);
      codes.set(code, new Set(tags));
      tags.forEach(key => counts[key]++);
    }
    for (const key of Object.keys(labels)) {
      if (!Number.isInteger(data.groups[key]?.count) || data.groups[key].count <= 0 || counts[key] !== data.groups[key].count) throw new Error('Index count mismatch: ' + key);
    }
    const memberships = code => Object.keys(labels).filter(key => codes.get(normalizeCode(code))?.has(key));
    const matches = (code, condition) => condition === 'all' || (filters.includes(condition) && !!codes.get(normalizeCode(code))?.has(condition));
    return Object.freeze({
      memberships, matches,
      // Call AFTER any existing sort, limit and filters; never adds or renumbers rows.
      filter: (rows, condition, getCode = row => row.code) => rows.filter(row => matches(getCode(row), condition)),
      version: data.version, basisNote: data.basis_note,
    });
  }
  const api = Object.freeze({create, normalizeCode, labels, filters});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.IndexMemberships = api;
})(typeof window === 'undefined' ? globalThis : window);
