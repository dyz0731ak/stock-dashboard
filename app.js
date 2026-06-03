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
      <div class="change num ${signCls(it.change)}">${it.change > 0 ? '▲' : it.change < 0 ? '▼' : ''} ${signTxt(fmt(Math.abs(it.change), it.decimals))}</div>
    `;
    grid.appendChild(card);
  });
  $('#updIdx').textContent = '更新 ' + clock(data.updated_at);
}

/* ============================================================
   2. 決算速報（決算サプライズ / 修正など zone別）
   ============================================================ */
let flashData = { jp: null, us: null };
let flashMode = 'jp';

function renderFlash() {
  const d = flashData[flashMode];
  const body = $('#flashBody');
  if (!d) { body.innerHTML = '<div class="skeleton">データなし</div>'; return; }

  // モード切替ピル（日本株 / 米国株）
  const pills = $('#flashPills');
  pills.innerHTML = `
    <span class="pill ${flashMode === 'jp' ? 'active' : ''}" data-m="jp">日本株 <span class="n">${flashData.jp ? flashData.jp.total : 0}</span></span>
    <span class="pill ${flashMode === 'us' ? 'active' : ''}" data-m="us">米国株 <span class="n">${flashData.us ? flashData.us.total : 0}</span></span>`;
  pills.querySelectorAll('.pill').forEach(p => p.onclick = () => { flashMode = p.dataset.m; renderFlash(); });

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

/* ============================================================
   3. 本日の決算発表（events.json の jp/us earnings）
   ============================================================ */
let eventsData = null;
let earnMode = 'us';
function renderEarn() {
  const d = eventsData; if (!d) return;
  const pills = $('#earnPills');
  pills.innerHTML = `
    <span class="pill ${earnMode === 'jp' ? 'active' : ''}" data-m="jp">日本株 <span class="n">${d.jp_earnings.length}</span></span>
    <span class="pill ${earnMode === 'us' ? 'active' : ''}" data-m="us">米国株 <span class="n">${d.us_earnings.length}</span></span>`;
  pills.querySelectorAll('.pill').forEach(p => p.onclick = () => { earnMode = p.dataset.m; renderEarn(); });

  const list = earnMode === 'jp' ? d.jp_earnings : d.us_earnings;
  const body = $('#earnBody'); body.innerHTML = '';
  if (!list.length) { body.innerHTML = '<div class="skeleton">本日の予定なし</div>'; }
  list.slice(0, 12).forEach(it => {
    const row = el('div', 'row-item');
    const id = earnMode === 'jp' ? it.code : it.symbol;
    const tag = it.time_jst_label || it.quarter || '';
    row.innerHTML = `
      <span class="r-code">${id}</span>
      <span class="r-name">${it.name}</span>
      ${tag ? `<span class="r-tag">${tag}</span>` : ''}`;
    body.appendChild(row);
  });
  $('#updEarn').textContent = '更新 ' + clock(d.updated_at);
}

/* ============================================================
   4. 市場ニュース
   ============================================================ */
function renderNews(d) {
  const body = $('#newsBody'); body.innerHTML = '';
  d.items.forEach(it => {
    const row = el('a', 'row-item');
    row.href = it.url; row.target = '_blank'; row.rel = 'noopener';
    row.innerHTML = `
      <span class="r-date">${(it.date || '').split(' ')[0]}</span>
      <span class="r-name">${it.title}</span>
      <span class="r-tag">${it.source_label || it.source}</span>`;
    body.appendChild(row);
  });
  $('#updNews').textContent = '更新 ' + clock(d.updated_at);
}

/* ============================================================
   5. サマリー統計
   ============================================================ */
function renderStats(jp, ev, flashJp) {
  const top = jp.all_stocks[0];
  const cards = [
    { k: 'ストップ高', v: jp.stop_high_count, u: '銘柄', meta: '本日の値幅制限到達' },
    { k: 'ストップ高接近', v: jp.near_stop_count, u: '銘柄', meta: '5%以内に接近' },
    { k: '最高騰落率', v: top ? top.change_pct : '—', u: '%', meta: top ? top.name : '', cls: 'up' },
    { k: '決算発表(速報)', v: flashJp ? flashJp.total : 0, u: '件', meta: '日本株・前営業日分' },
    { k: '本日の経済指標', v: ev ? ev.economic.length : 0, u: '件', meta: '★重要度付き' },
  ];
  const strip = $('#statStrip'); strip.innerHTML = '';
  cards.forEach(c => {
    const s = el('div', 'stat');
    s.innerHTML = `<div class="k">${c.k}</div><div class="v ${c.cls || ''}">${c.v}<small>${c.u}</small></div><div class="meta">${c.meta}</div>`;
    strip.appendChild(s);
  });
}

/* ============================================================
   6. 急騰ランキング
   ============================================================ */
let rankData = { jp: null, us: null };
let rankMode = 'jp';

function renderRank() {
  const jp = rankData.jp, us = rankData.us;
  // タブ（日本株 / 米国株）
  const jpN = jp ? jp.all_stocks.length : 0;
  const usN = us ? (us.gainers || []).length : 0;
  const pills = $('#rankPills');
  pills.innerHTML = `
    <span class="pill ${rankMode === 'jp' ? 'active' : ''}" data-m="jp">日本株 <span class="n">${jpN}</span></span>
    <span class="pill ${rankMode === 'us' ? 'active' : ''}" data-m="us">米国株 <span class="n">${usN}</span></span>`;
  pills.querySelectorAll('.pill').forEach(p => p.onclick = () => { rankMode = p.dataset.m; renderRank(); });

  const t = el('table', 'rank');
  const body = $('#rankBody'); body.innerHTML = '';

  if (rankMode === 'jp') {
    if (!jp) { body.innerHTML = '<div class="skeleton">データなし</div>'; return; }
    $('#rankSub').textContent = '日本株・値上がり率上位';
    $('#updRank').textContent = '更新 ' + clock(jp.updated_at);
    const rows = [...jp.all_stocks].filter(s => s.change_pct != null)
      .sort((a, b) => parseFloat(b.change_pct) - parseFloat(a.change_pct)).slice(0, 15);
    t.innerHTML = `<thead><tr>
      <th>コード</th><th>銘柄</th><th>市場</th>
      <th class="r">株価</th><th class="r">前日比</th><th class="r">騰落率</th><th class="r">状態</th>
    </tr></thead>`;
    const tb = el('tbody');
    rows.forEach(s => {
      const pct = parseFloat(s.change_pct);
      const tr = el('tr');
      tr.innerHTML = `
        <td class="t-code">${s.code}</td>
        <td><div class="t-name">${s.name}</div><div class="t-sec">${s.sector || ''}</div></td>
        <td><span class="pill-mkt">${s.market}</span></td>
        <td class="r num">${fmt(s.price)}円</td>
        <td class="r num ${signCls(pct)}">${s.change_amount}</td>
        <td class="r num ${signCls(pct)}"><b>${pctTxt(pct)}</b></td>
        <td class="r">${s.is_stop_high ? '<span class="st-tag">S高</span>' : ''}</td>`;
      tb.appendChild(tr);
    });
    t.appendChild(tb);
  } else {
    if (!us) { body.innerHTML = '<div class="skeleton">データなし</div>'; return; }
    $('#rankSub').textContent = '米国株・値上がり率上位';
    $('#updRank').textContent = '更新 ' + clock(us.updated_at);
    const rows = [...(us.gainers || [])].filter(s => s.change_pct != null)
      .sort((a, b) => parseFloat(b.change_pct) - parseFloat(a.change_pct)).slice(0, 15);
    t.innerHTML = `<thead><tr>
      <th>ティッカー</th><th>銘柄</th><th>セクター</th>
      <th class="r">株価</th><th class="r">前日比</th><th class="r">騰落率</th>
    </tr></thead>`;
    const tb = el('tbody');
    rows.forEach(s => {
      const pct = parseFloat(s.change_pct);
      const tr = el('tr');
      tr.innerHTML = `
        <td class="t-code">${s.symbol}</td>
        <td><div class="t-name">${s.name || s.symbol}</div></td>
        <td><span class="pill-mkt">${s.sector || s.sector_en || '—'}</span></td>
        <td class="r num">$${fmt(s.price, 2)}</td>
        <td class="r num ${signCls(pct)}">${s.change > 0 ? '+' : ''}${fmt(s.change, 2)}</td>
        <td class="r num ${signCls(pct)}"><b>${pctTxt(pct)}</b></td>`;
      tb.appendChild(tr);
    });
    t.appendChild(tb);
  }
  body.appendChild(t);
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
  const total = items.reduce((s, i) => s + i.value, 0);
  const scaled = items.map(i => ({ ...i, area: i.value / total * w * h }));
  const out = [];
  let rest = scaled.slice();
  let cx = x, cy = y, cw = w, ch = h;
  function worst(row, len) {
    const sum = row.reduce((s, r) => s + r.area, 0);
    const max = Math.max(...row.map(r => r.area)), min = Math.min(...row.map(r => r.area));
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
let heatData = { jp: null, us: null };
let heatMode = 'jp';
const HEAT_META = {
  jp: { title: '日経225 ヒートマップ', label: '日本株', count: 80 },
  us: { title: 'S&P500 ヒートマップ', label: '米国株', count: 100 },
};

function renderHeatmap() {
  const d = heatData[heatMode];
  // タブ
  const pills = $('#heatPills');
  pills.innerHTML = `
    <span class="pill ${heatMode === 'jp' ? 'active' : ''}" data-m="jp">日本株</span>
    <span class="pill ${heatMode === 'us' ? 'active' : ''}" data-m="us">米国株</span>`;
  pills.querySelectorAll('.pill').forEach(p => p.onclick = () => { heatMode = p.dataset.m; renderHeatmap(); });

  $('#heatTitle').textContent = HEAT_META[heatMode].title;
  const box = $('#heatmap');
  if (!d) { box.innerHTML = '<div class="skeleton">データなし</div>'; return; }

  const W = box.clientWidth || 1100, H = box.clientHeight || 520;
  const items = [...d.items]
    .filter(s => s.market_cap > 0)
    .sort((a, b) => b.market_cap - a.market_cap)
    .slice(0, HEAT_META[heatMode].count)
    .map(s => ({ value: s.market_cap, name: s.name || s.symbol, pct: s.change_pct, code: s.code || s.symbol }));
  const tiles = squarify(items, 0, 0, W, H);
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
}

/* ============================================================
   Boot
   ============================================================ */
async function boot() {
  const tasks = {
    futures: getJSON('data/futures.json'),
    japan: getJSON('data/japan_stocks.json'),
    usStocks: getJSON('data/us_stocks.json'),
    flashJp: getJSON('data/earnings_flash.json'),
    flashUs: getJSON('data/earnings_flash_us.json'),
    events: getJSON('data/events.json'),
    news: getJSON('data/market_news.json'),
    nikkei: getJSON('data/nikkei225.json'),
    sp500: getJSON('data/sp500.json'),
    themes: getJSON('data/themes.json'),
  };
  const get = async k => { try { return await tasks[k]; } catch (e) { console.warn(k, e); return null; } };

  const [futures, japan, usStocks, flashJp, flashUs, events, news, nikkei, sp500, themes] = await Promise.all(
    ['futures', 'japan', 'usStocks', 'flashJp', 'flashUs', 'events', 'news', 'nikkei', 'sp500', 'themes'].map(get)
  );

  if (futures) renderIndices(futures);
  if (flashJp || flashUs) { flashData = { jp: flashJp, us: flashUs }; flashMode = flashJp ? 'jp' : 'us'; renderFlash(); $('#navFlash').textContent = (flashJp ? flashJp.total : 0); }
  if (events) {
    eventsData = events; renderEarn();
    const ec = events.economic || [];
    eventMode = ec.filter(e => e.country === 'JP').length > ec.filter(e => e.country === 'US').length ? 'jp' : 'us';
    renderEvents(events);
  }
  if (news) renderNews(news);
  if (japan || usStocks) { rankData = { jp: japan, us: usStocks }; rankMode = japan ? 'jp' : 'us'; renderRank(); }
  if (japan) renderStats(japan, events, flashJp);
  if (themes) { themesData = themes; renderThemes(); }
  if (nikkei || sp500) { heatData = { jp: nikkei, us: sp500 }; heatMode = nikkei ? 'jp' : 'us'; renderHeatmap(); }

  // 最終更新（最新のタイムスタンプ）
  const stamps = [futures, japan, events, news, nikkei].filter(Boolean).map(d => d.updated_at).filter(Boolean);
  if (stamps.length) {
    const latest = stamps.sort().pop();
    $('#lastUpdated').textContent = '最終更新 ' + clock(latest) + '（' + timeAgo(latest) + '）';
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
  window._rz = setTimeout(() => { if (heatData.jp || heatData.us) renderHeatmap(); }, 300);
});

boot();
