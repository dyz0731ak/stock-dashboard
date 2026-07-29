/* ============================================================
   投資の砦 — 森スタイル ダッシュボード レンダラ
   砦の data/*.json をそのまま読み込んで描画する。
   ============================================================ */

const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };

// 数値整形
const fmt = (n, dec = 0) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
const signCls = v => v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
const signTxt = v => (v > 0 ? '+' : '') + v;
const pctTxt = v => (v > 0 ? '+' : '') + Number(v).toFixed(2) + '%';
const escHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

// 上げ赤・下げ緑（日本式）の背景色
function pctBadge(pct) {
  const up = pct > 0, dn = pct < 0;
  const bg = up ? 'var(--up-soft)' : dn ? 'var(--down-soft)' : '#eef1f5';
  const fg = up ? 'var(--up)' : dn ? 'var(--down)' : 'var(--ink-3)';
  return `style="background:${bg};color:${fg}"`;
}

async function getJSON(path) {
  const r = await fetch(path + '?_=' + Date.now());
  if (!r.ok) throw new Error(path + ' ' + r.status);
  return r.json();
}

function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso), now = new Date();
  const m = Math.floor((now - d) / 60000);
  if (m < 1) return 'たった今';
  if (m < 60) return m + '分前';
  const h = Math.floor(m / 60);
  if (h < 24) return h + '時間前';
  return Math.floor(h / 24) + '日前';
}
function clock(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
function ageHours(iso) {
  if (!iso) return Infinity;
  return (Date.now() - new Date(iso).getTime()) / 3600000;
}
const isFresh = (data, maxHours) => !!data && data.fetch_status !== 'stale' && ageHours(data.updated_at) <= maxHours;
function updateLabel(data, maxHours) {
  if (!data) return '取得できません';
  const suffix = data.is_fallback ? `・${data.scope || '代替データ'}` : '';
  if (!isFresh(data, maxHours)) return `要確認 ${clock(data.updated_at)}（${timeAgo(data.updated_at)}）${suffix}`;
  return `更新 ${clock(data.updated_at)}${suffix}`;
}

/* ---------- ミニ・スパークライン (SVG) ---------- */
function sparkline(chart, up) {
  if (!chart || chart.length < 2) return '';
  const vals = chart.map(c => c.c);
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  const W = 160, H = 46, n = vals.length;
  const pts = vals.map((v, i) => [i / (n - 1) * W, H - 4 - ((v - min) / span) * (H - 8)]);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const area = `M0 ${H} L` + pts.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L') + ` L${W} ${H} Z`;
  const col = up ? 'var(--up)' : 'var(--down)';
  const fill = up ? 'rgba(217,45,32,.10)' : 'rgba(14,138,95,.10)';
  const id = 'g' + Math.random().toString(36).slice(2, 8);
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <path d="${area}" fill="${fill}"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

/* ============================================================
   1. 指数・先物カード
   ============================================================ */
function renderIndices(data) {
  const grid = $('#idxGrid');
  grid.innerHTML = '';
  data.items.forEach(it => {
    const up = it.pct > 0, dn = it.pct < 0;
    const card = el('div', 'idx-card');
    card.innerHTML = `
      ${sparkline(it.chart, up)}
      <div class="head">
        <span class="label">${it.label}</span>
        <span class="pct-badge" ${pctBadge(it.pct)}>${pctTxt(it.pct)}</span>
      </div>
      <div class="price num ${signCls(it.pct)}">${fmt(it.price, it.decimals)}</div>
      <div class="change num ${signCls(it.change)}">${it.change > 0 ? '▲' : it.change < 0 ? '▼' : ''} ${fmt(Math.abs(it.change), it.decimals)}</div>
    `;
    grid.appendChild(card);
  });
  $('#updIdx').textContent = '更新 ' + clock(data.updated_at);
}

/* ============================================================
   2. 決算速報（決算サプライズ / 修正など zone別）
   ============================================================ */
let flashData = null;

function renderFlash() {
  const d = flashData;
  const body = $('#flashBody');
  if (!d) { body.innerHTML = '<div class="skeleton">データなし</div>'; return; }

  const pills = $('#flashPills');
  pills.innerHTML = `<span class="pill active">日本株 <span class="n">${d.total || 0}</span></span>`;

  $('#flashSub').textContent = `${d.article_date} 発表分 ・ 計${d.total}件`;
  $('#updFlash').textContent = '更新 ' + clock(d.updated_at);

  body.innerHTML = '';
  d.groups.forEach(g => {
    if (!g.items || !g.items.length) return;
    const zone = el('div', 'flash-zone zone-' + g.zone);
    zone.appendChild(el('div', 'zone-label', `<span class="zone-tag">${g.display}</span><span style="color:var(--ink-3);font-weight:500">${g.items.length}件</span>`));
    g.items.slice(0, 6).forEach(it => {
      const chips = (it.chips || []).map(c => {
        const cls = c.direction === 'up' ? 'pos' : c.direction === 'down' ? 'neg' : '';
        const strong = c.strength === 'strong' ? 'font-weight:700' : '';
        return `<span class="chip ${cls}" style="${strong}">${c.label} ${c.value}</span>`;
      }).join('');
      const item = el('div', 'flash-item');
      item.innerHTML = `
        <span class="time">${it.time || ''}</span>
        <span class="code">${it.code}</span>
        <div class="body">
          <div class="nm">${it.name}</div>
          <div class="nar">${it.narrative || ''}</div>
          <div class="chips">${chips}</div>
        </div>`;
      zone.appendChild(item);
    });
    body.appendChild(zone);
  });
}

let eventsData = null;
/* ============================================================
   6. 急騰ランキング
   ============================================================ */
let rankData = null;
let rankView = 'table';

function rankRows() {
  return [...(rankData?.all_stocks || [])]
    .filter(s => s.change_pct != null)
    .sort((a, b) => Number(b.change_pct) - Number(a.change_pct))
    .slice(0, 30);
}

function miniCandleChart(chart) {
  const closes = chart?.closes || [];
  if (closes.length < 2) return '<div class="mini-nochart">チャート準備中</div>';
  // 約6か月分の日足（営業日ベースで最大130本）を表示する。
  const n = Math.min(130, closes.length);
  const c = closes.slice(-n).map(Number);
  const o = (chart.opens || closes).slice(-n).map(Number);
  const h = (chart.highs || closes).slice(-n).map(Number);
  const l = (chart.lows || closes).slice(-n).map(Number);
  const v = (chart.volumes || []).slice(-n).map(x => Number(x || 0));
  const valid = [...h, ...l].filter(Number.isFinite);
  const min = Math.min(...valid), max = Math.max(...valid), span = max - min || 1;
  const maxVol = Math.max(...v, 1);
  const W = 440, H = 210, priceH = 156, volumeTop = 166, volumeH = 34;
  const step = W / n, bodyW = Math.max(2, Math.min(6, step * .58));
  const y = val => 8 + (max - val) / span * (priceH - 16);
  const grid = [0, 1, 2, 3].map(i => {
    const gy = 8 + i * (priceH - 16) / 3;
    return `<line x1="0" y1="${gy}" x2="${W}" y2="${gy}" class="mc-grid"/>`;
  }).join('');
  const candles = c.map((close, i) => {
    if (![o[i], h[i], l[i], close].every(Number.isFinite)) return '';
    const x = step * i + step / 2;
    const rising = close >= o[i];
    const color = rising ? '#26a69a' : '#ef5350';
    const top = Math.min(y(o[i]), y(close));
    const height = Math.max(1.4, Math.abs(y(o[i]) - y(close)));
    const vh = v[i] / maxVol * volumeH;
    return `<line x1="${x.toFixed(1)}" y1="${y(h[i]).toFixed(1)}" x2="${x.toFixed(1)}" y2="${y(l[i]).toFixed(1)}" stroke="${color}" stroke-width="1"/>
      <rect x="${(x-bodyW/2).toFixed(1)}" y="${top.toFixed(1)}" width="${bodyW.toFixed(1)}" height="${height.toFixed(1)}" fill="${color}" rx=".5"/>
      <rect x="${(x-bodyW/2).toFixed(1)}" y="${(volumeTop+volumeH-vh).toFixed(1)}" width="${bodyW.toFixed(1)}" height="${vh.toFixed(1)}" fill="${color}" opacity=".45"/>`;
  }).join('');
  const lastY = y(c[c.length - 1]);
  return `<svg class="mini-candle" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="直近約6か月の日足チャート">
    ${grid}<line x1="0" y1="${lastY.toFixed(1)}" x2="${W}" y2="${lastY.toFixed(1)}" class="mc-last"/>
    ${candles}
  </svg>`;
}

function renderRankTable(rows) {
  const t = el('table', 'rank');
  t.innerHTML = `<thead><tr><th class="rank-col">順位</th><th>コード</th><th>銘柄</th><th>市場</th><th class="r">株価</th><th class="r">前日比</th><th class="r">騰落率</th><th class="r">状態</th></tr></thead>`;
  const tb = el('tbody');
  rows.forEach((s, i) => {
    const pct = Number(s.change_pct);
    const tr = el('tr');
    const code = s.code;
    const change = s.change_amount;
    tr.innerHTML = `<td><span class="rank-no ${i < 3 ? 'top' : ''}">${i + 1}</span></td>
      <td class="t-code">${escHtml(code)}</td>
      <td><div class="t-name">${escHtml(s.name || code)}</div><div class="t-sec">${escHtml(s.sector || '')}</div></td>
      <td><span class="pill-mkt">${escHtml(s.market || '—')}</span></td>
      <td class="r num">${fmt(s.price)}円</td>
      <td class="r num ${signCls(change)}">${change == null ? '—' : (Number(change) > 0 ? '+' : '') + fmt(change, Number.isInteger(Number(change)) ? 0 : 2)}</td>
      <td class="r num ${signCls(pct)}"><b>${pctTxt(pct)}</b></td>
      <td class="r">${s.is_stop_high ? '<span class="st-tag">S高</span>' : ''}</td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  return t;
}

function renderRankCharts(rows) {
  const grid = el('div', 'rank-chart-grid');
  rows.forEach((s, i) => {
    const pct = Number(s.change_pct);
    const card = el('article', 'rank-chart-card');
    card.innerHTML = `<div class="rank-chart-head">
      <span class="rank-no ${i < 3 ? 'top' : ''}">${i + 1}</span>
      <div><b>${escHtml(s.name || s.symbol)}</b><small>${escHtml(s.code || s.symbol)}・${escHtml(s.market || s.sector || '')}・6か月日足</small></div>
      <div class="rank-chart-price"><b class="num">${fmt(s.price)}円</b><span class="num ${signCls(pct)}">${pctTxt(pct)}</span></div>
    </div>${miniCandleChart(s.chart)}</article>`;
    grid.appendChild(card);
  });
  return grid;
}

function renderRank() {
  const jp = rankData;
  const jpN = jp ? jp.all_stocks.length : 0;
  const pills = $('#rankPills');
  pills.innerHTML = `<span class="pill active">日本株 <span class="n">${jpN}</span></span>`;

  const body = $('#rankBody'); body.innerHTML = '';

  if (!jp) { body.innerHTML = '<div class="skeleton">データなし</div>'; return; }
  if (!isFresh(jp, 36)) {
    body.innerHTML = `<div class="data-notice">日本株ランキングの更新を確認中です。古いランキングは表示していません。<br><small>最終取得 ${clock(jp.updated_at)}（${timeAgo(jp.updated_at)}）</small></div>`;
    $('#rankSub').textContent = '日本株・取得確認中';
    $('#updRank').textContent = updateLabel(jp, 36);
    return;
  }
  $('#rankSub').textContent = `${jp.scope || '日本株・全市場'}・値上がり率上位${jp.is_fallback ? '（代替表示）' : ''}`;
  $('#updRank').textContent = updateLabel(jp, 36);

  const views = $('#rankViews');
  const availableViews = [['table', '一覧'], ['chart', 'ミニチャート']];
  views.innerHTML = availableViews.map(([key, label]) =>
    `<button type="button" class="rank-view-btn ${rankView === key ? 'active' : ''}" data-v="${key}">${label}</button>`
  ).join('');
  views.querySelectorAll('.rank-view-btn').forEach(btn => btn.onclick = () => {
    rankView = btn.dataset.v;
    renderRank();
  });

  const rows = rankRows();
  body.appendChild(
    rankView === 'chart' ? renderRankCharts(rows)
      : renderRankTable(rows)
  );
}

/* ============================================================
   6.5 テーマ株ランキング（themes.json・構成銘柄から算出）
   ============================================================ */
let themesData = null;
let themeSort = 'week';
const THEME_SORT = {
  week: { key: 'week_pct', label: '週間', sub: '週間上昇率順 / 構成銘柄から算出' },
  month: { key: 'month_pct', label: '月間', sub: '月間上昇率順 / 構成銘柄から算出' },
  day: { key: 'day_pct', label: '前日比', sub: '前日比順 / 構成銘柄から算出' },
};

// spark配列（正規化価格パス）→ SVG
function themeSpark(arr, up) {
  if (!arr || arr.length < 2) return '';
  const min = Math.min(...arr), max = Math.max(...arr), span = (max - min) || 1;
  const W = 64, H = 26, n = arr.length;
  const pts = arr.map((v, i) => [i / (n - 1) * W, H - 3 - ((v - min) / span) * (H - 6)]);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const col = up ? 'var(--up)' : 'var(--down)';
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="display:block"><path d="${line}" fill="none" stroke="${col}" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
}

function renderThemes() {
  const d = themesData;
  const pills = $('#themePills');
  pills.innerHTML = Object.entries(THEME_SORT).map(([k, v]) =>
    `<span class="pill ${themeSort === k ? 'active' : ''}" data-s="${k}">${v.label}</span>`).join('');
  pills.querySelectorAll('.pill').forEach(p => p.onclick = () => { themeSort = p.dataset.s; renderThemes(); });

  const body = $('#themesBody');
  if (!d || !d.themes) { body.innerHTML = '<div class="skeleton">データなし</div>'; return; }
  $('#themesSub').textContent = THEME_SORT[themeSort].sub;
  $('#updThemes').textContent = '更新 ' + clock(d.updated_at);

  const key = THEME_SORT[themeSort].key;
  const themes = [...d.themes].sort((a, b) => b[key] - a[key]);

  const t = el('table', 'rank');
  t.innerHTML = `<thead><tr>
    <th style="width:40px">#</th><th>テーマ</th><th style="width:70px">推移</th>
    <th class="r">1週間</th><th class="r">1ヶ月</th><th class="r">前日比</th>
    <th class="r">勝率</th><th class="r">銘柄</th><th>注目銘柄</th>
  </tr></thead>`;
  const tb = el('tbody');
  themes.forEach((th, i) => {
    const chips = (th.top || []).slice(0, 3).map(m =>
      `<span class="theme-chip"><b>${m.name}</b> <span class="${signCls(m.week_pct)}">${pctTxt(m.week_pct)}</span></span>`).join('');
    const tr = el('tr');
    tr.innerHTML = `
      <td><span class="rank-no${i < 3 ? ' top' : ''}">${i + 1}</span></td>
      <td><div class="t-name">${th.hot ? '<span class="hot-badge">注目度急上昇中</span><br>' : ''}${th.name}</div></td>
      <td>${themeSpark(th.spark, th.week_pct >= 0)}</td>
      <td class="r num ${signCls(th.week_pct)}"><b>${pctTxt(th.week_pct)}</b></td>
      <td class="r num ${signCls(th.month_pct)}">${pctTxt(th.month_pct)}</td>
      <td class="r num ${signCls(th.day_pct)}">${pctTxt(th.day_pct)}</td>
      <td class="r num">${th.win_rate.toFixed(0)}%</td>
      <td class="r num">${th.count}社</td>
      <td><div class="theme-chips">${chips}</div></td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  body.innerHTML = ''; body.appendChild(t);
}

/* ============================================================
   7. 経済指標・イベント
   ============================================================ */
let eventMode = 'us';
function renderEvents(d) {
  if (d) eventsData = d;
  const data = eventsData;
  const all = data.economic || [];
  const jp = all.filter(e => e.country === 'JP');
  const us = all.filter(e => e.country === 'US');

  // タブ（日本 / 米国）
  const pills = $('#eventPills');
  pills.innerHTML = `
    <span class="pill ${eventMode === 'jp' ? 'active' : ''}" data-m="jp">日本 <span class="n">${jp.length}</span></span>
    <span class="pill ${eventMode === 'us' ? 'active' : ''}" data-m="us">米国 <span class="n">${us.length}</span></span>`;
  pills.querySelectorAll('.pill').forEach(p => p.onclick = () => { eventMode = p.dataset.m; renderEvents(); });

  const src = eventMode === 'jp' ? jp : us;
  const body = $('#eventsBody'); body.innerHTML = '';
  if (!src.length) { body.innerHTML = '<div class="skeleton">予定なし</div>'; }
  const WD = ['日', '月', '火', '水', '木', '金', '土'];
  const evDate = iso => {
    if (!iso) return '';
    const p = iso.split('-');
    const d = new Date(+p[0], +p[1] - 1, +p[2]);
    return `${+p[1]}/${+p[2]}(${WD[d.getDay()]})`;
  };
  // "53.3" "118K" "-1.5%" などを数値化（サプライズ判定用）
  const parseNum = v => {
    if (v == null || v === '') return null;
    let s = String(v).replace(/[,\s%]/g, '').replace(/[人件社円ドル件戸棟]/g, '')
      .replace(/兆/, 'e12').replace(/億/, 'e8').replace(/万/, 'e4')
      .replace(/K$/i, 'e3').replace(/M$/i, 'e6').replace(/B$/i, 'e9');
    const n = parseFloat(s);
    return isNaN(n) ? null : n;
  };
  // 結果が予想を上回った/下回った→ good_when を加味して市場プラス(赤)/マイナス(緑)
  const surpriseCls = ev => {
    const a = parseNum(ev.actual), f = parseNum(ev.forecast);
    if (a == null || f == null || a === f || ev.good_when === 'neutral') return 'flat';
    const higher = a > f;
    const positive = (ev.good_when === 'high' && higher) || (ev.good_when === 'low' && !higher);
    return positive ? 'up' : 'down';
  };

  const list = [...src].sort((a, b) => new Date(a.datetime_jst) - new Date(b.datetime_jst)).slice(0, 16);
  list.forEach(ev => {
    const stars = '★'.repeat(ev.stars || 0);
    const released = ev.status === 'released';
    const isToday = ev.date === data.target_today;

    // 数値系の指標か（予想/前回/結果のいずれかを持つ）。会見・要人発言は数値なし。
    const hasData = !!(ev.actual || ev.forecast || ev.prior);
    const parts = [];
    if (ev.actual) parts.push(`結果 <b class="${surpriseCls(ev)}">${ev.actual}</b>`);
    else if (released && hasData) parts.push(`結果 <span class="flat">—</span>`);
    if (ev.forecast) parts.push(`予想 <span class="num">${ev.forecast}</span>`);
    if (ev.prior) parts.push(`前回 <span class="num">${ev.prior}</span>`);
    const metrics = parts.length ? `<div class="ev-metrics">${parts.join('<span class="sep">・</span>')}</div>` : '';

    const statusChip = released
      ? `<span class="ev-status done">発表済み</span>`
      : `<span class="ev-status soon">発表前</span>`;

    const row = el('div', 'row-item ev-row');
    row.innerHTML = `
      <span class="r-datetime">
        <span class="r-d${isToday ? ' today' : ''}">${evDate(ev.date)}</span>
        <span class="r-t num">${ev.time_jst || ''}</span>
      </span>
      <span class="r-tag" style="min-width:40px;text-align:center">${(ev.country_label || '').slice(0, 3)}</span>
      <div class="ev-body">
        <div class="r-name">${ev.event_ja || ev.event}${isToday ? ' <span style="color:var(--up);font-size:10px;font-weight:700">●本日</span>' : ''}</div>
        ${metrics}
      </div>
      ${statusChip}
      <span class="ev-stars">${stars}</span>`;
    body.appendChild(row);
  });
  $('#updEvents').textContent = '更新 ' + clock(data.updated_at);
}

/* ============================================================
   8. ヒートマップ（squarified treemap）
   ============================================================ */
function heatColor(pct) {
  const p = Math.max(-3, Math.min(3, pct)) / 3;
  if (p > 0) { // 上げ＝赤
    const t = p;
    return `rgb(${Math.round(233 + (217 - 233) * t)},${Math.round(237 + (45 - 237) * t)},${Math.round(240 + (32 - 240) * t)})`;
  } else { // 下げ＝緑
    const t = -p;
    return `rgb(${Math.round(233 + (14 - 233) * t)},${Math.round(237 + (138 - 237) * t)},${Math.round(240 + (95 - 240) * t)})`;
  }
}
// squarified treemap layout
function squarify(items, x, y, w, h) {
  items = items.filter(i => Number.isFinite(i.value) && i.value > 0);
  if (!items.length || !Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return [];
  const total = items.reduce((s, i) => s + i.value, 0);
  const scaled = items.map(i => ({ ...i, area: i.value / total * w * h }));
  const out = [];
  let rest = scaled.slice();
  let cx = x, cy = y, cw = w, ch = h;
  function worst(row, len) {
    const sum = row.reduce((s, r) => s + r.area, 0);
    const max = Math.max(...row.map(r => r.area)), min = Math.min(...row.map(r => r.area));
    if (!sum || !min || !len) return Infinity;
    return Math.max((len * len * max) / (sum * sum), (sum * sum) / (len * len * min));
  }
  while (rest.length) {
    const horizontal = cw >= ch;
    const len = horizontal ? ch : cw;
    let row = [];
    while (rest.length) {
      const next = row.concat(rest[0]);
      if (row.length && worst(row, len) < worst(next, len)) break;
      row.push(rest.shift());
    }
    const sum = row.reduce((s, r) => s + r.area, 0);
    const thick = sum / len;
    if (!Number.isFinite(thick) || thick <= 0) break;
    let off = horizontal ? cy : cx;
    row.forEach(r => {
      const sz = r.area / thick;
      if (horizontal) out.push({ ...r, x: cx, y: off, w: thick, h: sz });
      else out.push({ ...r, x: off, y: cy, w: sz, h: thick });
      off += sz;
    });
    if (horizontal) { cx += thick; cw -= thick; } else { cy += thick; ch -= thick; }
  }
  return out;
}
let heatData = null;
let heatResizeObserver = null;
let heatRenderTimer = null;

function renderHeatmap() {
  const d = heatData;
  const pills = $('#heatPills');
  pills.innerHTML = '<span class="pill active">日本株</span>';

  $('#heatTitle').textContent = '日経225 ヒートマップ';
  const box = $('#heatmap');
  if (!d) { box.innerHTML = '<div class="skeleton">データなし</div>'; return; }

  const W = box.clientWidth, H = box.clientHeight;
  if (W < 100 || H < 100) {
    clearTimeout(heatRenderTimer);
    heatRenderTimer = setTimeout(renderHeatmap, 150);
    return;
  }
  const items = [...d.items]
    .filter(s => Number.isFinite(Number(s.market_cap)) && Number(s.market_cap) > 0)
    .sort((a, b) => b.market_cap - a.market_cap)
    .slice(0, 80)
    .map(s => ({
      value: Number(s.market_cap),
      name: s.name || s.symbol,
      pct: Number(s.change_pct) || 0,
      code: s.code || s.symbol,
    }));
  const tiles = squarify(items, 0, 0, W, H);
  if (!tiles.length) {
    box.innerHTML = '<div class="skeleton">ヒートマップを再読み込みしています</div>';
    return;
  }
  box.innerHTML = '';
  tiles.forEach(t => {
    const tile = el('div', 'hm-tile');
    tile.style.cssText = `left:${t.x}px;top:${t.y}px;width:${t.w}px;height:${t.h}px;background:${heatColor(t.pct)}`;
    tile.title = `${t.name} (${t.code}) ${pctTxt(t.pct)}`;
    if (t.w > 42 && t.h > 26) {
      const nm = t.name.length > 6 && t.w < 90 ? t.name.slice(0, 5) + '…' : t.name;
      tile.innerHTML = `<div class="hm-nm">${nm}</div>${t.h > 40 ? `<div class="hm-pct">${pctTxt(t.pct)}</div>` : ''}`;
    }
    box.appendChild(tile);
  });
  $('#updHeat').textContent = '更新 ' + clock(d.updated_at);

  if (!heatResizeObserver && 'ResizeObserver' in window) {
    let lastWidth = W;
    heatResizeObserver = new ResizeObserver(entries => {
      const nextWidth = Math.round(entries[0]?.contentRect?.width || 0);
      if (nextWidth < 100 || Math.abs(nextWidth - lastWidth) < 2) return;
      lastWidth = nextWidth;
      clearTimeout(heatRenderTimer);
      heatRenderTimer = setTimeout(renderHeatmap, 100);
    });
    heatResizeObserver.observe(box);
  }
}

/* ============================================================
   Boot
   ============================================================ */
async function boot() {
  const tasks = {
    futures: getJSON('data/futures.json'),
    japan: getJSON('data/japan_stocks.json'),
    flashJp: getJSON('data/earnings_flash.json'),
    events: getJSON('data/events.json'),
    nikkei: getJSON('data/nikkei225.json'),
    themes: getJSON('data/themes.json'),
    health: getJSON('data/health.json'),
  };
  const get = async k => { try { return await tasks[k]; } catch (e) { console.warn(k, e); return null; } };

  const [futures, japan, flashJp, events, nikkei, themes, health] = await Promise.all(
    ['futures', 'japan', 'flashJp', 'events', 'nikkei', 'themes', 'health'].map(get)
  );

  if (futures) renderIndices(futures);
  if (flashJp) { flashData = flashJp; renderFlash(); $('#navFlash').textContent = flashJp.total || 0; }
  if (events) {
    const ec = events.economic || [];
    eventMode = ec.filter(e => e.country === 'JP').length > ec.filter(e => e.country === 'US').length ? 'jp' : 'us';
    renderEvents(events);
  }
  if (japan) {
    rankData = japan;
    renderRank();
  }
  if (themes) { themesData = themes; renderThemes(); }
  if (nikkei) { heatData = nikkei; renderHeatmap(); }

  // 利用者向けには内部監査の件数を出さず、確認済みの更新時刻だけを表示
  if (health) {
    $('#lastUpdated').textContent = `データ更新 ${clock(health.checked_at)}`;
  } else {
    const stamps = [futures, japan, events, nikkei].filter(Boolean).map(d => d.updated_at).filter(Boolean);
    if (stamps.length) {
      const latest = stamps.sort().pop();
      $('#lastUpdated').textContent = '最終取得 ' + clock(latest);
    }
  }

  // ナビのスクロールスパイ
  const links = [...document.querySelectorAll('#navTabs a')];
  const spy = () => {
    let cur = links[0];
    links.forEach(l => { const s = document.querySelector(l.getAttribute('href')); if (s && s.getBoundingClientRect().top < 120) cur = l; });
    links.forEach(l => l.classList.toggle('active', l === cur));
  };
  window.addEventListener('scroll', spy, { passive: true });
}

window.addEventListener('resize', () => { /* ヒートマップ再描画はデバウンス */
  clearTimeout(window._rz);
  window._rz = setTimeout(() => { if (heatData) renderHeatmap(); }, 300);
});

boot();
