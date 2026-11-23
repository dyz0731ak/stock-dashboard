const storageKey = 'toride.chart.watchlist';
const defaults = ['5802', '593A', '5803', '7203'];
const maxEntries = 30;
const quoteInterval = 300_000;
const percent = new Intl.NumberFormat('ja-JP', { style: 'percent', maximumFractionDigits: 2, signDisplay: 'exceptZero' });
const price = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });
const date = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', dateStyle: 'medium' });

function readEntries() {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey));
    if (Array.isArray(stored)) return [...new Set(stored.filter(code =>
      typeof code === 'string' && /^[0-9][0-9A-Z]{3}$/.test(code)))].slice(0, maxEntries);
  } catch {
    // A blocked or invalid browser store still allows a session-local list.
  }
  return defaults.slice();
}

export function createWatchlist({ getCode, getName, selectCode }) {
  const rows = document.getElementById('watch-rows');
  const add = document.getElementById('watch-add');
  const status = document.getElementById('watch-status');
  const quotes = new Map();
  const entries = readEntries();
  const pending = new Set();
  const quoteChecks = new Map();
  let activeRequests = 0;

  function paintQuote(row, symbol) {
    const quote = quotes.get(symbol);
    row.cells[1].textContent = quote ? price.format(quote.close) : '—';
    row.cells[2].textContent = quote?.change != null ? percent.format(quote.change) : '—';
    row.cells[2].className = quote?.change > 0 ? 'watch-up' : quote?.change < 0 ? 'watch-down' : '';
    row.cells[1].title = row.cells[2].title = quote ? date.format(new Date(quote.time * 1000)) + ' JST' : '';
  }

  function updateSelection() {
    add.disabled = entries.includes(getCode()) || entries.length >= maxEntries;
    for (const row of rows.rows) {
      const selected = row.dataset.code === getCode();
      row.dataset.current = String(selected);
      const open = row.querySelector('.watch-open');
      if (selected) open.setAttribute('aria-current', 'true');
      else open.removeAttribute('aria-current');
      row.querySelector('.watch-open span').textContent = getName(row.dataset.code) || '';
    }
  }

  function addRow(symbol) {
    const row = rows.insertRow();
    row.dataset.code = symbol;
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'watch-open';
    const code = document.createElement('strong');
    code.textContent = symbol;
    open.append(code, document.createElement('span'));
    row.addEventListener('click', event => {
      if (!event.target.closest('.watch-remove')) selectCode(symbol);
    });
    open.addEventListener('keydown', event => {
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
      const next = event.key === 'ArrowUp' ? row.previousElementSibling : row.nextElementSibling;
      if (next) {
        event.preventDefault();
        next.querySelector('.watch-open').focus();
        selectCode(next.dataset.code);
      }
    });
    row.insertCell().append(open);
    row.insertCell();
    row.insertCell();
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'watch-remove';
    remove.textContent = '×';
    remove.setAttribute('aria-label', symbol + 'をウォッチリストから削除');
    remove.addEventListener('click', () => {
      entries.splice(entries.indexOf(symbol), 1);
      const next = row.nextElementSibling || row.previousElementSibling;
      row.remove();
      save();
      updateSelection();
      status.textContent = symbol + 'を削除しました。';
      (next?.querySelector('.watch-remove') || (add.disabled ? document.getElementById('symbol') : add)).focus();
    });
    row.insertCell().append(remove);
    paintQuote(row, symbol);
  }

  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(entries));
    } catch {
      // Keep the edited list usable for this page even if persistence is unavailable.
    }
  }

  async function loadQuote(symbol) {
    activeRequests++;
    pending.add(symbol);
    try {
      const response = await fetch(`../data/stock_history/${symbol}/1d.json?summary=1`, {
        signal: AbortSignal.timeout(12000), cache: 'no-cache',
      });
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (data.code !== symbol || data.interval !== '1d') throw new Error();
      const last = data.bars?.at(-1);
      const previous = data.bars?.at(-2);
      const quote = Number.isFinite(last?.close) && Number.isFinite(last.time) ? {
        close: last.close, time: last.time,
        change: previous?.close > 0 ? (last.close - previous.close) / previous.close : null,
      } : null;
      if (quote && (!quotes.get(symbol) || quote.time >= quotes.get(symbol).time)) quotes.set(symbol, quote);
      const row = [...rows.rows].find(row => row.dataset.code === symbol);
      if (row) paintQuote(row, symbol);
    } catch {
      // Retain the previous quote if the refresh fails.
    } finally {
      quoteChecks.set(symbol, Date.now());
      activeRequests--;
      pending.delete(symbol);
      loadQuotes();
    }
  }

  function loadQuotes() {
    if (document.hidden) return;
    const dueBefore = Date.now() - quoteInterval;
    for (const symbol of entries) {
      if (activeRequests >= 3) break;
      if (!pending.has(symbol) && (quoteChecks.get(symbol) ?? 0) <= dueBefore) loadQuote(symbol);
    }
  }

  add.addEventListener('click', () => {
    const symbol = getCode();
    if (entries.includes(symbol) || entries.length >= maxEntries) return;
    entries.push(symbol);
    addRow(symbol);
    save();
    updateSelection();
    status.textContent = symbol + 'を追加しました。';
    rows.lastElementChild.querySelector('.watch-open').focus();
    quoteChecks.delete(symbol);
    loadQuotes();
  });

  entries.forEach(addRow);
  updateSelection();
  loadQuotes();
  setInterval(loadQuotes, 15_000);
  document.addEventListener('visibilitychange', loadQuotes);
  return { updateSelection };
}
