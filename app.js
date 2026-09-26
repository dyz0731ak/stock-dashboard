/* ============================================================
   投資の砦 — 株式市場監視室 ダッシュボード レンダラ
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
  const bg = up ? 'var(--up-soft)' : dn ? 'var(--down-soft)' : 'var(--surface-2)';
  const fg = up ? 'var(--up)' : dn ? 'var(--down)' : 'var(--ink-3)';
  return `style="background:${bg};color:${fg}"`;
}

async function getJSON(path) {
  for(let attempt=0;attempt<2;attempt++) {
    try {
      const r = await fetch(path + '?_=' + Date.now(), { signal: AbortSignal.timeout(10000), cache: 'no-store' });
      if (!r.ok) throw new Error(path + ' ' + r.status);
      return await r.json();
    } catch(error) {
      if(attempt)throw error;
      await new Promise(resolve=>setTimeout(resolve,500));
    }
  }
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
  if (!iso || !Number.isFinite(new Date(iso).getTime())) return '不明';
  return new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo', month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso));
}
function ageHours(iso) { return iso ? (Date.now() - new Date(iso).getTime()) / 3600000 : Infinity; }
const isFresh = (data, maxHours) => !!data && !['stale','error'].includes(data.fetch_status) &&
  ageHours(data.fetched_at || data.updated_at) >= -5/60 &&
  (data.valid_until ? Date.now() <= new Date(data.valid_until).getTime() : ageHours(data.updated_at) <= maxHours);
function updateLabel(data, maxHours) {
  if (!data) return '未取得';
  const label = !isFresh(data, maxHours) ? '取得失敗・期限切れ' : ({partial:'一部取得',fallback:'代替取得'}[data.fetch_status] || '取得済み');
  return `${label} ｜ 最終取得 ${clock(data.fetched_at || data.updated_at)} JST`;
}
function dataNotice(data, hours) {
  return `<div class="data-notice">${escHtml(updateLabel(data,hours))}<br>期限切れの数値は表示していません。<br><small>最終試行 ${clock(data?.last_attempt_at)} JST${data?.session_date ? ' ・ 取引日 '+escHtml(data.session_date) : ''}</small></div>`;
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
   1. 現物指数・為替・金スポット
   ============================================================ */
const marketSpecs = [
  ['nk225','^N225','日経225',2,'円','INDEX'],
  ['dow','^DJI','NYダウ',2,'pt','INDEX'],
  ['nasdaq','^IXIC','NASDAQ総合指数',2,'pt','INDEX'],
  ['usdjpy','JPY=X','USD/JPY',3,'円 / 米ドル','CURRENCY'],
  ['sox','^SOX','SOX指数',2,'pt','INDEX'],
  ['gold','XAU','金スポット',2,'USD / トロイオンス','SPOT'],
];
const tseSpecs = [
  ['tse-prime','TsePrimeMarketIndex','東証プライム市場指数',2,'pt','INDEX'],
  ['tse-standard','TseStandardMarketIndex','東証スタンダード市場指数',2,'pt','INDEX'],
  ['tse-growth','TseGrowthMarketIndex','東証グロース市場指数',2,'pt','INDEX'],
];
function renderIndices(data, group='market') {
  const tse = group === 'tse', specs = tse ? tseSpecs : marketSpecs;
  const grid = $(tse ? '#tseGrid' : '#idxGrid');
  grid.innerHTML = specs.map(([id,ticker,label,decimals,unit,type]) => {
    const it = data?.items?.find(row=>row.id===id && row.ticker===ticker && row.instrument_type===type);
    const cached = it?.cache_status === 'previous' && ageHours(it.fetched_at)>=0 && ageHours(it.fetched_at)<=24 && Date.now()<=Date.parse(it.cache_until);
    const fresh = ((isFresh(data,8) && isFresh(it,8)) || cached) && Number.isFinite(it?.price) && it.price>0;
    const chartButton = tse ? '' : `<button class="index-chart-button" type="button" data-market-chart="${id}" aria-label="${label}のローソク足チャートを開く" aria-haspopup="dialog"><span>ローソク足 ›</span></button>`;
    if (!fresh) return `<div class="idx-card index-unavailable"><div class="head"><span class="label">${label}</span></div><div class="price num">—</div><div class="index-unit">${unit}</div><div class="price-date">取得待ち・期限切れ</div>${chartButton}</div>`;
    const hasChange = Number.isFinite(it.pct) && Number.isFinite(it.change);
    const badge = hasChange ? `<span class="pct-badge" ${pctBadge(it.pct)}>${pctTxt(it.pct)}</span>` : '<span class="spot-badge">スポット</span>';
    const change = hasChange ? `<div class="change num ${signCls(it.change)}">前日比 ${it.change>0?'▲':it.change<0?'▼':''} ${fmt(Math.abs(it.change),decimals)}</div>` : '<div class="change change-unavailable">前日比 —</div>';
    const source = safeExternalUrl(it.source_url);
    return `<div class="idx-card" data-index="${id}">
      ${sparkline(it.chart,it.pct>0)}
      <div class="head"><span class="label">${label}</span>${badge}</div>
      <div class="price num">${fmt(it.price,decimals)}<span class="index-unit">${unit}</span></div>
      ${change}<div class="price-date">${cached ? '<span class="cached-quote">前回取得値</span> ' : ''}基準 ${escHtml(clock(it.as_of))} JST</div>
      <a class="index-source" href="${escHtml(source)}" target="_blank" rel="noopener noreferrer">${escHtml(it.source_label)}</a>${chartButton}
    </div>`;
  }).join('');
  $(tse ? '#updTse' : '#updIdx').textContent = updateLabel(data,8);
}

/* ============================================================
   2. 決算速報（決算サプライズ / 修正など zone別）
   ============================================================ */
let flashData = null;

function safeExternalUrl(value) {
  const url = String(value || '').trim();
  return /^https?:\/\//i.test(url) ? url : '';
}

function tdnetDocumentUrl(value) {
  const url = safeExternalUrl(value);
  const match = url.match(/\/(1401\d{14,})\.pdf(?:\?.*)?$/i);
  if (match) return `https://www.release.tdnet.info/inbs/${match[1]}.pdf`;
  return /\.pdf(?:\?.*)?$/i.test(url) ? url : '';
}

function earningsReferenceLinks(it) {
  const code = String(it.code || '').replace(/[^0-9A-Z]/gi, '');
  const original = safeExternalUrl(it.url);
  const documentUrl = safeExternalUrl(it.document_url) || tdnetDocumentUrl(original);
  const articleUrl = safeExternalUrl(it.article_url) || (!tdnetDocumentUrl(original) ? original : '');
  const candidates = [
    { url: documentUrl, label: '決算短信・適時開示PDF', primary: true },
    ...(it.documents || []).map(doc=>({url:safeExternalUrl(doc.url),label:doc.title,primary:true})),
    { url: articleUrl, label: '決算速報・解説を読む' },
    { url: safeExternalUrl(it.ir_url) || (code ? `https://irbank.net/${code}/ir` : ''), label: '過去の決算資料' },
    { url: safeExternalUrl(it.news_url) || (code ? `https://s.kabutan.jp/stocks/${code}/news/?news_category_id=3` : ''), label: '関連する決算記事' },
  ];
  const seen = new Set();
  return candidates.filter(link => link.url && !seen.has(link.url) && seen.add(link.url));
}

function renderFlash() {
  const d = flashData;
  const body = $('#flashBody');
  if (!d) { body.innerHTML = '<div class="skeleton">データなし</div>'; return; }

  const shown = Math.min(12, (d.highlights || []).length || d.total || 0);
  $('#flashSub').textContent = `${d.article_date} 発表分 ・ 重要度上位${shown}件${d.checked_date && d.checked_date!==d.article_date ? '（本日の開示も確認済み）' : ''}`;
  $('#updFlash').textContent = updateLabel(d, 36);

  body.innerHTML = '';
  const rows = d.highlights || (d.groups || []).flatMap(g => g.items || []);
  if (!rows.length) {
    body.innerHTML = `<div class="skeleton">${escHtml(d.empty_message || '重要決算を確認中です')}</div>`;
    return;
  }
  if (d.cache_status==='previous') body.append(el('p','data-notice',escHtml(d.fetch_warning)));
  const list = el('div', 'flash-list');
  rows.slice(0, 12).forEach(it => {
    const referenceLinks = earningsReferenceLinks(it);
    const referenceButtons = referenceLinks.map(link => `
      <a class="flash-detail-link${link.primary ? ' primary' : ''}" href="${escHtml(link.url)}" target="_blank" rel="noopener">
        <span>${escHtml(link.label)}</span><span aria-hidden="true">↗</span>
      </a>`).join('');
    const chips = (it.chips || []).map(c => {
      const cls = c.direction === 'up' ? 'pos' : c.direction === 'down' ? 'neg' : '';
      const strong = c.strength === 'strong' ? 'font-weight:700' : '';
      return `<span class="chip ${cls}" style="${strong}">${c.label} ${c.value}</span>`;
    }).join('');
    const item = el('article', `flash-item ${it.impact_zone || 'decision'}`);
    item.tabIndex = 0;
    item.setAttribute('role', 'button');
    item.setAttribute('aria-expanded', 'false');
    item.innerHTML = `
      <div class="flash-top">
        <span class="nm">${escHtml(it.name || '')}</span>
        <span class="code">${escHtml(it.code || '')}</span>
        <span class="flash-published">${escHtml(it.published_label || `${d.article_date} ${it.time || ''}発表`)}</span>
        <span class="impact-label">${escHtml(it.impact_label || '注目決算')}</span>
      </div>
      <div class="flash-business">${escHtml(it.company_summary || '事業説明を取得できませんでした')}</div>
      <div class="nar">${escHtml(it.narrative || '')}</div>
      <div class="flash-numbers">${(it.key_numbers || []).map(n=>`<div><span>${escHtml(n.label)}</span><strong>${escHtml(n.value)}</strong><small>${escHtml(n.comparison)}</small></div>`).join('')}</div>
      <div class="chips">${chips}</div>
      <div class="impact-summary"><strong>注目理由：</strong>${escHtml(it.impact_summary || '通期計画への進捗と今後の見通しを確認したい決算です。')}</div>
      <div class="flash-chart-toggle">詳細・根拠を見る</div>
      <div class="flash-detail-panel" hidden>
        <div class="flash-reference">
          <div class="flash-detail-title">根拠資料・関連記事</div>
          <div class="flash-detail-note">表示内容は決算短信・適時開示をもとに整理しています。数値や会社予想は原資料でもご確認ください。</div>
          <div class="flash-detail-links">${referenceButtons}</div>
        </div>
        ${it.company_explanation ? `<p class="flash-explanation">${escHtml(it.company_explanation)}</p>` : ''}
        <p class="flash-detail-note">${escHtml(it.consensus_status || '')}</p>
      </div>`;
    const setOpen = open => {
      item.classList.toggle('open', open);
      item.setAttribute('aria-expanded', String(open));
      item.querySelector('.flash-detail-panel').hidden = !open;
      item.querySelector('.flash-chart-toggle').textContent = open ? '詳細を閉じる' : '詳細・根拠を見る';
    };
    const toggle = () => {
      const willOpen = !item.classList.contains('open');
      list.querySelectorAll('.flash-item.open').forEach(other => {
        if (other === item) return;
        other.classList.remove('open');
        other.setAttribute('aria-expanded', 'false');
        other.querySelector('.flash-detail-panel').hidden = true;
        other.querySelector('.flash-chart-toggle').textContent = '詳細・根拠を見る';
      });
      setOpen(willOpen);
    };
    item.addEventListener('click', event => {
      if (event.target.closest('.flash-detail-link')) return;
      toggle();
    });
    item.addEventListener('keydown', event => {
      if ((event.key === 'Enter' || event.key === ' ') && !event.target.closest('.flash-detail-link')) {
        event.preventDefault();
        toggle();
      }
    });
    list.appendChild(item);
  });
  body.appendChild(list);
}

let marketNewsData = null;
/* ============================================================
   6. 急騰ランキング
   ============================================================ */
let rankData = null;
let ptsRankData = null;
let rankMarket = 'tse';
let rankView = 'table';

function rankRows() {
  const data = rankMarket === 'pts' ? ptsRankData : rankData;
  return [...(data?.all_stocks || [])]
    .filter(s => s.change_pct != null)
    .sort((a, b) => Number(b.change_pct) - Number(a.change_pct))
    .slice(0, 30);
}

function miniCandleChart(chart, maxPoints = 130, ariaLabel = '直近約6か月の日足チャート') {
  const closes = chart?.closes || [];
  if (closes.length < 2) return '<div class="mini-nochart">チャート準備中</div>';
  const n = Math.min(maxPoints, closes.length);
  const c = closes.slice(-n).map(value=>value==null ? NaN : Number(value));
  const o = (chart.opens || closes).slice(-n).map(value=>value==null ? NaN : Number(value));
  const h = (chart.highs || closes).slice(-n).map(value=>value==null ? NaN : Number(value));
  const l = (chart.lows || closes).slice(-n).map(value=>value==null ? NaN : Number(value));
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
    const color = rising ? '#ef5350' : '#26a69a';
    const top = Math.min(y(o[i]), y(close));
    const height = Math.max(1.4, Math.abs(y(o[i]) - y(close)));
    const vh = v[i] / maxVol * volumeH;
    return `<line x1="${x.toFixed(1)}" y1="${y(h[i]).toFixed(1)}" x2="${x.toFixed(1)}" y2="${y(l[i]).toFixed(1)}" stroke="${color}" stroke-width="1"/>
      <rect x="${(x-bodyW/2).toFixed(1)}" y="${top.toFixed(1)}" width="${bodyW.toFixed(1)}" height="${height.toFixed(1)}" fill="${color}" rx=".5"/>
      <rect x="${(x-bodyW/2).toFixed(1)}" y="${(volumeTop+volumeH-vh).toFixed(1)}" width="${bodyW.toFixed(1)}" height="${vh.toFixed(1)}" fill="${color}" opacity=".45"/>`;
  }).join('');
  const lastY = y([...c].reverse().find(Number.isFinite));
  return `<svg class="mini-candle" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${escHtml(ariaLabel)}">
    ${grid}<line x1="0" y1="${lastY.toFixed(1)}" x2="${W}" y2="${lastY.toFixed(1)}" class="mc-last"/>
    ${candles}
  </svg>`;
}

function renderRankTable(rows) {
  const isPts = rankMarket === 'pts';
  const t = el('table', 'rank');
  t.innerHTML = `<thead><tr><th class="rank-col">順位</th><th>コード</th><th>銘柄</th><th>市場</th><th class="r">${isPts ? 'PTS価格' : '株価'}</th><th class="r">${isPts ? '東証終値比' : '前日比'}</th><th class="r">騰落率</th><th class="r">${isPts ? '出来高' : '状態'}</th></tr></thead>`;
  const tb = el('tbody');
  rows.forEach((s, i) => {
    const pct = Number(s.change_pct);
    const tr = el('tr');
    const code = s.code;
    const change = s.change_amount;
    tr.innerHTML = `<td><span class="rank-no ${i < 3 ? 'top' : ''}">${i + 1}</span></td>
      <td class="t-code">${escHtml(code)}</td>
      <td><a class="t-name company-trigger" href="https://s.kabutan.jp/stocks/${encodeURIComponent(code)}/" data-company-code="${escHtml(code)}" data-company-name="${escHtml(s.name || code)}" aria-haspopup="dialog">${escHtml(s.name || code)} <span class="company-hint">詳細 ›</span></a><div class="t-sec company-summary" data-company-summary="${escHtml(code)}">${escHtml(window.CompanyProfiles?.summary(code) || '事業内容は企業詳細へ')}</div></td>
      <td><span class="pill-mkt">${escHtml(isPts ? (s.market_tse || 'PTS') : (s.market || '—'))}</span></td>
      <td class="r num">${fmt(s.price)}円</td>
      <td class="r num ${signCls(change)}">${change == null ? '—' : (Number(change) > 0 ? '+' : '') + fmt(change, Number.isInteger(Number(change)) ? 0 : 2)}</td>
      <td class="r num ${signCls(pct)}"><b>${pctTxt(pct)}</b></td>
      <td class="r">${isPts ? `<span class="num">${s.volume == null ? '—' : fmt(s.volume) + '株'}</span>` : (s.is_stop_high ? '<span class="st-tag">S高</span>' : '')}</td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  return t;
}

function renderRankCharts(rows) {
  const isPts = rankMarket === 'pts';
  const grid = el('div', 'rank-chart-grid');
  rows.forEach((s, i) => {
    const pct = Number(s.change_pct);
    const card = el('article', 'rank-chart-card');
    card.innerHTML = `<div class="rank-chart-head">
      <span class="rank-no ${i < 3 ? 'top' : ''}">${i + 1}</span>
      <div><a class="company-trigger" href="https://s.kabutan.jp/stocks/${encodeURIComponent(s.code)}/" data-company-code="${escHtml(s.code)}" data-company-name="${escHtml(s.name || s.code)}" aria-haspopup="dialog"><b>${escHtml(s.name || s.symbol)}</b> <span class="company-hint">詳細 ›</span></a><small class="company-summary" data-company-summary="${escHtml(s.code)}">${escHtml(window.CompanyProfiles?.summary(s.code) || '事業内容は企業詳細へ')}</small><small>${escHtml(s.code || s.symbol)}・${escHtml(isPts ? (s.market_tse || '夜間PTS') : (s.market || s.sector || ''))}・${isPts ? '東証' : ''}6か月日足</small></div>
      <div class="rank-chart-price"><b class="num">${fmt(s.price)}円</b><span class="num ${signCls(pct)}">${pctTxt(pct)}</span></div>
    </div>${miniCandleChart(s.chart)}</article>`;
    grid.appendChild(card);
  });
  return grid;
}

function renderRank() {
  const jp = rankData;
  const pts = ptsRankData;
  const data = rankMarket === 'pts' ? pts : jp;
  const jpN = isFresh(jp,36) ? jp?.all_stocks?.length || 0 : '—';
  const ptsN = isFresh(pts,36) ? pts?.all_stocks?.length || 0 : '—';
  const pills = $('#rankPills');
  pills.innerHTML = `<button type="button" class="pill ${rankMarket === 'tse' ? 'active' : ''}" data-market="tse">${jp?.is_fallback ? '日経225代替' : '東証全市場'} <span class="n">${jpN}</span></button>
    <button type="button" class="pill ${rankMarket === 'pts' ? 'active' : ''}" data-market="pts">夜間PTS <span class="n">${ptsN}</span></button>`;
  pills.querySelectorAll('[data-market]').forEach(button => button.onclick = () => {
    rankMarket = button.dataset.market;
    renderRank();
  });

  const body = $('#rankBody'); body.innerHTML = '';

  if (!data) { body.innerHTML = dataNotice(null,36); $('#updRank').textContent='取得失敗'; return; }
  const maxAge = 36;
  $('#rankViews').innerHTML = '';
  if (!isFresh(data, maxAge)) {
    body.innerHTML = `<div class="data-notice">${rankMarket === 'pts' ? '夜間PTS' : '日本株'}ランキングの更新を確認中です。古いランキングは表示していません。<br><small>最終取得 ${clock(data.fetched_at || data.updated_at)} JST ・ 最終試行 ${clock(data.last_attempt_at)} JST</small></div>`;
    $('#rankSub').textContent = `${rankMarket === 'pts' ? '夜間PTS' : '日本株'}・取得確認中`;
    $('#updRank').textContent = updateLabel(data, maxAge);
    return;
  }
  const ptsDate = data.session_date ? `・${data.session_date.replaceAll('-', '/')}取引` : '';
  const ptsAsOf = data.as_of ? `・${clock(data.as_of)}現在` : '';
  $('#rankSub').textContent = rankMarket === 'pts'
    ? `夜間PTS${ptsDate}${ptsAsOf}・東証終値比の値上がり率上位`
    : `${data.scope || '日本株・全市場'}・値上がり率上位${data.is_fallback ? '（代替表示）' : ''}`;
  $('#updRank').textContent = updateLabel(data, maxAge);
  if (rankMarket === 'tse') $('#rankSub').textContent += ` ・ ${data.session_date || '対象日不明'} ・ 上位${data.all_stocks?.length || 0}件${data.fetch_status === 'fallback' ? '（代替取得）' : ''}`;

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
  $('#updThemes').textContent = updateLabel(d, 36);

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
   7. 市場のいま — 日本株に影響する重要トピックス
   ============================================================ */
function renderMarketNews(d) {
  if (d) marketNewsData = d;
  const data = marketNewsData;
  const body = $('#marketNewsBody');
  const items = (data?.items || []).slice(0, 10);
  body.innerHTML = '';
  if (!items.length) {
    body.innerHTML = '<div class="skeleton">重要ニュースを確認中です</div>';
    return;
  }
  items.forEach((news, i) => {
    const card = el('a', `market-news-card${i === 0 ? ' lead' : ''}`);
    card.href = news.url || '#';
    card.target = '_blank';
    card.rel = 'noopener';
    const sectors = (news.watch_sectors || []).slice(0, 4)
      .map(s => `<span>${escHtml(s)}</span>`).join('');
    card.innerHTML = `
      <div class="market-news-meta">
        <span class="market-topic">${escHtml(news.topic || '市場全体')}</span>
        <span>${escHtml(news.source_label || '主要メディア')}</span>
        <time>${escHtml(news.date || '')}</time>
      </div>
      <h3>${escHtml(news.title || '')}</h3>
      <div class="market-impact">
        <b>日本株への見方</b>
        <p>${escHtml(news.impact_summary || '')}</p>
      </div>
      <div class="market-news-foot">
        <div class="market-sectors">${sectors}</div>
        <span class="market-read">記事を読む</span>
      </div>`;
    body.appendChild(card);
  });
  $('#updMarketNews').textContent = updateLabel(data, 12);
}

/* ============================================================
   8. ヒートマップ（squarified treemap）
   ============================================================ */
function heatColor(pct) {
  const amount = Math.min(1,Math.abs(pct)/3);
  const neutral=[30,46,63], target=pct>0?[153,47,61]:[22,115,85];
  return `rgb(${neutral.map((v,i)=>Math.round(v+(target[i]-v)*amount)).join(',')})`;
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
  if (!isFresh(d,12)) { box.innerHTML = dataNotice(d,12); return; }

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
  $('#updHeat').textContent = updateLabel(d, 36);

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
const feeds = [
  ['tse_indices','tse_indices.json','東証市場別指数','tseGrid','updTse',8,d=>renderIndices(d,'tse')],
  ['market_indices','market_indices.json','主要マーケット指標','idxGrid','updIdx',8,d=>renderIndices(d)],
  ['japan','japan_stocks.json','東証全市場','rankBody','updRank',36,d=>{rankData=d;renderRank();}],
  ['pts','pts_ranking.json','夜間PTS',null,null,36,d=>{ptsRankData=d;renderRank();}],
  ['themes','themes.json','テーマ株','themesBody','updThemes',8,d=>{themesData=d;renderThemes();}],
  ['flash','earnings_flash.json','決算速報','flashBody','updFlash',36,d=>{flashData=d;renderFlash();$('#navFlash').textContent=Math.min(12,(d.highlights||[]).length||d.total||0);}],
  ['news','market_news.json','市場ニュース','marketNewsBody','updMarketNews',12,d=>renderMarketNews(d)],
  ['heat','nikkei225.json','ヒートマップ','heatmap','updHeat',12,d=>{heatData=d;renderHeatmap();}],
];
const loadedFeeds = {};
let refreshing = false;
function renderStatus() {
  const good = feeds.filter(([key,,,,,hours])=>isFresh(loadedFeeds[key],hours)).length;
  const warnings = feeds.some(([key])=>['fallback','partial'].includes(loadedFeeds[key]?.fetch_status));
  $('#lastUpdated').textContent = `${good}/${feeds.length}項目 有効${warnings ? ' ・ 一部代替／部分取得' : ''}`;
}
async function boot() {
  if (refreshing) return;
  refreshing = true;
  await Promise.allSettled(feeds.map(async ([key,file,label,body,upd,hours,render])=> {
    let data;
    try {
      data = await getJSON('data/'+file);
      loadedFeeds[key] = data;
      if (['japan','pts','market_indices','tse_indices'].includes(key)) render(data);
      else if (isFresh(data,hours)) render(data);
      else if (body) { if(key==='heat') heatData=null; $('#'+body).innerHTML = dataNotice(data,hours); }
      if (upd && (key!=='japan' || rankMarket==='tse')) $('#'+upd).textContent = updateLabel(data,hours);
    } catch (error) {
      console.error(JSON.stringify({event:'feed_load_failed',dataset:file,time:new Date().toISOString(),error:String(error)}));
      data = {...loadedFeeds[key], fetch_status:'stale', fetch_error:String(error)};
      if(key==='market_indices') data.items=(data.items||[]).map(row=>{
        const fetched=Date.parse(row.fetched_at);
        return {...row,cache_status:'previous',cache_until:Number.isFinite(fetched)?new Date(fetched+24*3600000).toISOString():null};
      });
      if(key==='flash' && isFresh(loadedFeeds[key],hours)) data={...loadedFeeds[key],fetch_status:'fallback',cache_status:'previous',fetch_warning:'通信に失敗したため前回取得済みの開示を表示しています。'};
      loadedFeeds[key] = data;
      if (key==='market_indices' || key==='tse_indices') render(data);
      else if (key==='japan') { rankData=data; renderRank(); }
      else if (key==='pts') { ptsRankData=data; renderRank(); }
      else if (key==='flash' && isFresh(data,hours)) render(data);
      else if (body) { if(key==='heat') heatData=null; $('#'+body).innerHTML=dataNotice(data,hours); }
      if (upd && (key!=='japan' || rankMarket==='tse')) $('#'+upd).textContent='取得失敗';
    }
    renderStatus();
  }));
  refreshing = false;
}
const links = [...document.querySelectorAll('#navTabs a')];
window.addEventListener('scroll', () => {
  let current = links[0];
  links.forEach(link=> { const section=document.querySelector(link.getAttribute('href')); if(section && section.getBoundingClientRect().top<120) current=link; });
  links.forEach(link=>link.classList.toggle('active',link===current));
}, {passive:true});
setInterval(boot, 60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden) boot();});

window.addEventListener('resize', () => { /* ヒートマップ再描画はデバウンス */
  clearTimeout(window._rz);
  window._rz = setTimeout(() => { if (heatData) renderHeatmap(); }, 300);
});

boot();
