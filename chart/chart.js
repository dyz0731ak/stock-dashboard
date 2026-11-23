import { withRsi } from './indicators.mjs';
import { createWatchlist } from './watchlist.mjs';

const $ = id => document.getElementById(id);
const controls = [...document.querySelectorAll('[data-interval]')];
const validCode = /^[0-9][0-9A-Z]{3}$/;
const url = new URL(location.href);
const input = $('symbol');
const message = $('search-message');
const status = $('status');
const refreshStatus = $('refresh-status');
const refreshInterval = 60_000;
const locale = { timeZone: 'Asia/Tokyo' };
const fullTime = new Intl.DateTimeFormat('ja-JP', { ...locale, dateStyle: 'medium', timeStyle: 'short' });
const shortDate = new Intl.DateTimeFormat('ja-JP', { ...locale, year: 'numeric', month: 'numeric', day: 'numeric' });
const hourMinute = new Intl.DateTimeFormat('ja-JP', { ...locale, hour: '2-digit', minute: '2-digit' });
const checkedTime = new Intl.DateTimeFormat('ja-JP', { ...locale, timeStyle: 'medium' });
const year = new Intl.DateTimeFormat('ja-JP', { ...locale, year: 'numeric' });
const monthDay = new Intl.DateTimeFormat('ja-JP', { ...locale, month: 'numeric', day: 'numeric' });
const price = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });
const up = '#32c5a8';
const down = '#f47382';
let code = url.searchParams.get('code')?.toUpperCase() || '593A';
if (!validCode.test(code)) code = '593A';
let interval = controls.some(b => b.dataset.interval === url.searchParams.get('interval'))
  ? url.searchParams.get('interval') : '1h';
let stocks = [];
let chart, candle, volume, band, rsi, sma, request;
let bars = [];
let byTime = new Map();
let intraday = false;
let refreshTimer, refreshAt;
let updateFailures = 0;
let inspectedTime;

const stockName = symbol => stocks.find(stock => stock.code === symbol)?.name;
const title = () => {
  const name = stockName(code);
  $('instrument').textContent = name ? `${name}（${code}）` : code;
};
const smaKey = 'toride.chart.sma';
let showSma = false;
try { showSma = localStorage.getItem(smaKey) === 'true'; } catch {}

function selectCode(next) {
  if (!chart) return;
  message.textContent = '';
  code = next;
  input.value = code;
  load();
}

const watchlist = createWatchlist({ getCode: () => code, getName: stockName, selectCode });
const date = time => new Date(time * 1000);

function resetRange() {
  const displayBars = interval === '5m' ? 125 : 95;
  if (bars.length <= displayBars) chart.timeScale().fitContent();
  else chart.timeScale().setVisibleLogicalRange({ from: bars.length - displayBars, to: bars.length + 4 });
}

function showReadout(bar) {
  $('prices').replaceChildren();
  if (!bar) return;
  const time = document.createElement('time');
  time.dateTime = date(bar.time).toISOString();
  time.textContent = (intraday ? fullTime : shortDate).format(date(bar.time));
  $('prices').append(time);
  for (const [label, value] of [
    ['始値', bar.open], ['高値', bar.high], ['安値', bar.low], ['終値', bar.close], ['出来高', bar.volume],
  ]) {
    const item = document.createElement('span');
    const number = document.createElement('b');
    number.textContent = value == null ? '—' : price.format(value);
    item.append(label + ' ', number);
    $('prices').append(item);
  }
  $('rsi-value').textContent = bar.rsi?.toFixed(2) ?? '—';
  $('sma-value').textContent = bar.sma?.toFixed(2) ?? '—';
}

function setupChart() {
  const { createChart, CandlestickSeries, HistogramSeries, BaselineSeries, LineSeries, LineStyle, CrosshairMode } =
    window.LightweightCharts;
  const host = $('chart');
  chart = createChart(host, {
    autoSize: true,
    layout: {
      background: { color: '#0d1928' }, textColor: '#a1b6c9',
      panes: { separatorColor: '#23374c', separatorHoverColor: '#34516a', enableResize: true },
    },
    localization: { locale: 'ja-JP', timeFormatter: time => (intraday ? fullTime : shortDate).format(date(time)) },
    grid: { vertLines: { color: '#18283a' }, horzLines: { color: '#18283a' } },
    rightPriceScale: { borderColor: '#23374c', minimumWidth: 68 },
    timeScale: {
      borderColor: '#23374c', rightOffset: 4,
      tickMarkFormatter: (time, type) => {
        if (intraday && type >= 3) return hourMinute.format(date(time));
        return (type === 0 ? year : monthDay).format(date(time));
      },
    },
    crosshair: { mode: CrosshairMode.Normal },
  });
  candle = chart.addSeries(CandlestickSeries, {
    upColor: up, downColor: down, wickUpColor: up, wickDownColor: down, borderVisible: false,
  });
  candle.priceScale().applyOptions({ scaleMargins: { top: .09, bottom: .23 } });
  volume = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' }, priceScaleId: '', lastValueVisible: false, priceLineVisible: false,
  });
  volume.priceScale().applyOptions({ scaleMargins: { top: .82, bottom: 0 } });
  band = chart.addSeries(BaselineSeries, {
    baseValue: { type: 'price', price: 30 },
    topFillColor1: '#9775e128', topFillColor2: '#9775e128', topLineColor: 'transparent',
    lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
  }, 1);
  const oscillator = {
    lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
    autoscaleInfoProvider: original => {
      const visible = original();
      return {
        ...visible,
        priceRange: {
          minValue: Math.min(20, visible?.priceRange?.minValue ?? 20),
          maxValue: Math.max(80, visible?.priceRange?.maxValue ?? 80),
        },
      };
    },
  };
  rsi = chart.addSeries(LineSeries, { ...oscillator, color: '#bb9cf5' }, 1);
  sma = chart.addSeries(LineSeries, { ...oscillator, color: '#f4cf68', visible: showSma }, 1);
  const applySma = () => {
    sma.applyOptions({ visible: showSma });
    $('sma-toggle').setAttribute('aria-pressed', String(showSma));
    $('sma-readout').hidden = !showSma;
  };
  applySma();
  $('sma-toggle').addEventListener('click', () => {
    showSma = !showSma;
    applySma();
    try { localStorage.setItem(smaKey, String(showSma)); } catch {}
  });
  rsi.priceScale().applyOptions({ scaleMargins: { top: .17, bottom: .07 } });
  for (const level of [30, 50, 70]) {
    rsi.createPriceLine({ price: level, color: '#576985', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
  }
  const [pricePane, rsiPane] = chart.panes();
  pricePane.setStretchFactor(.60);
  rsiPane.setStretchFactor(.40);
  const positionLegend = () => {
    $('rsi').style.setProperty('--rsi-top', `${pricePane.getHeight() + 7}px`);
  };
  requestAnimationFrame(() => {
    const priceElement = pricePane.getHTMLElement();
    new ResizeObserver(positionLegend).observe(priceElement || host);
    positionLegend();
  });
  chart.subscribeCrosshairMove(event => {
    inspectedTime = event.time;
    showReadout(byTime.get(inspectedTime) ?? bars.at(-1));
  });
  $('reset').addEventListener('click', resetRange);
}

function draw(data, preserveView = false) {
  const scale = chart.timeScale();
  const range = preserveView && bars.length ? scale.getVisibleLogicalRange() : null;
  let shift = 0;
  if (range) {
    if (range.to >= bars.length - 1) {
      shift = data.length - bars.length;
    } else {
      const anchorIndex = Math.max(0, Math.min(Math.floor(range.from), bars.length - 1));
      const nextIndex = data.findIndex(point => point.time >= bars[anchorIndex].time);
      if (nextIndex >= 0) shift = nextIndex - anchorIndex;
    }
  }
  bars = withRsi(data);
  byTime = new Map(bars.map(bar => [bar.time, bar]));
  chart.timeScale().applyOptions({ timeVisible: intraday });
  candle.setData(bars);
  volume.setData(bars.flatMap(bar => bar.volume == null ? [] : [{
    time: bar.time, value: bar.volume, color: bar.close >= bar.open ? '#32c5a876' : '#f4738276',
  }]));
  band.setData(bars.map(bar => ({ time: bar.time, value: 70 })));
  rsi.setData(bars.filter(bar => bar.rsi != null).map(bar => ({ time: bar.time, value: bar.rsi })));
  sma.setData(bars.filter(bar => bar.sma != null).map(bar => ({ time: bar.time, value: bar.sma })));
  showReadout(byTime.get(inspectedTime) ?? bars.at(-1));
  $('rsi').hidden = !bars.length;
  $('reset').disabled = !bars.length;
  if (range) scale.setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
  else if (bars.length) resetRange();
}

function updateAddress() {
  const next = new URL(location.href);
  next.searchParams.set('code', code);
  next.searchParams.set('interval', interval);
  history.replaceState(null, '', next);
}

function checkBars(data) {
  return Array.isArray(data) && data.every((point, i) =>
    [point.time, point.open, point.high, point.low, point.close].every(Number.isFinite) &&
    Number.isSafeInteger(point.time) && point.time > (data[i - 1]?.time ?? 0) &&
    point.low > 0 && point.low <= Math.min(point.open, point.close) &&
    point.high >= Math.max(point.open, point.close) &&
    (point.volume == null || (Number.isFinite(point.volume) && point.volume >= 0)));
}

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  if (document.hidden || request || refreshAt == null) return;
  refreshTimer = setTimeout(() => load(true), Math.max(0, refreshAt - Date.now()));
}

function changed(data) {
  return data.length !== bars.length || data.some((point, index) => {
    const previous = bars[index];
    return ['time', 'open', 'high', 'low', 'close', 'volume'].some(field => point[field] !== previous[field]);
  });
}

async function load(background = false) {
  if (background && (document.hidden || request)) return;
  clearTimeout(refreshTimer);
  request?.abort();
  const controller = new AbortController();
  request = controller;
  const timeout = setTimeout(() => controller.abort(), 12000);
  if (!background) {
    updateFailures = 0;
    inspectedTime = undefined;
    title();
    watchlist.updateSelection();
    updateAddress();
    for (const button of controls) button.setAttribute('aria-pressed', String(button.dataset.interval === interval));
    intraday = interval === '5m' || interval === '1h';
    draw([]);
    status.textContent = 'チャートを読み込み中…';
    refreshStatus.textContent = '';
  }
  try {
    const response = await fetch(`../data/stock_history/${code}/${interval}.json`, {
      signal: controller.signal, cache: 'no-cache',
    });
    if (!response.ok) throw new Error();
    const result = await response.json();
    if (request !== controller) return;
    if (result.code !== code || result.interval !== interval || !checkBars(result.bars)) throw new Error();
    if (background && bars.length && (!result.bars.length || result.bars.at(-1).time < bars.at(-1).time)) throw new Error();
    if (changed(result.bars)) draw(result.bars, background);
    const last = bars.at(-1);
    if (last) {
      const lastDate = (intraday ? fullTime : shortDate).format(date(last.time));
      const detail = `${result.source || '株価データ'} · 最終足 ${lastDate}${intraday ? ' JST' : ''} · ${bars.length}本`;
      const nextStatus = bars.length < 15 ? detail + ' · RSI算出には15本必要です' : detail;
      if (status.textContent !== nextStatus) status.textContent = nextStatus;
    } else {
      status.textContent = 'この時間足のデータがありません。';
    }
    refreshStatus.textContent = result.stale ? '配信元の更新待ち · 前回データを表示中' : `最終確認 ${checkedTime.format(new Date())} JST · 1分ごとに確認`;
    updateFailures = 0;
  } catch {
    if (request !== controller) return;
    updateFailures++;
    if (bars.length) refreshStatus.textContent = '更新できませんでした · 前回データを表示中';
    else status.textContent = '株価データを取得できませんでした。時間足を押すと再試行します。';
  } finally {
    clearTimeout(timeout);
    if (request === controller) {
      request = null;
      refreshAt = Date.now() + Math.min(refreshInterval * 2 ** updateFailures, 300_000);
      scheduleRefresh();
    }
  }
}

document.addEventListener('visibilitychange', scheduleRefresh);

const normalize = value => value.normalize('NFKC').trim().toUpperCase();

$('symbol-form').addEventListener('submit', event => {
  event.preventDefault();
  const query = normalize(input.value);
  const typedCode = query.match(/^([0-9][0-9A-Z]{3})(?:[ .]|$)/)?.[1];
  const exact = stocks.find(stock => normalize(stock.name) === query);
  const matches = stocks.filter(stock => normalize(stock.name).includes(query));
  const next = typedCode || exact?.code || (matches.length === 1 ? matches[0].code : null);
  if (!next) {
    message.textContent = matches.length > 1 ? '候補から選ぶか、銘柄コードを入力してください。' : '銘柄が見つかりません。銘柄コードでも検索できます。';
    return;
  }
  selectCode(next);
});

input.addEventListener('input', () => {
  const query = normalize(input.value);
  const matches = query ? stocks.filter(stock =>
    stock.code.startsWith(query) || normalize(stock.name).includes(query)) : [];
  $('symbols').replaceChildren(...matches.slice(0, 20).map(stock => {
    const option = document.createElement('option');
    option.value = `${stock.code} ${stock.name}`;
    return option;
  }));
});

for (const button of controls) button.addEventListener('click', () => {
  if (!chart) return;
  interval = button.dataset.interval;
  load();
});

input.value = code;
title();
if (window.LightweightCharts) {
  setupChart();
  load();
} else {
  status.textContent = 'チャートの初期化に失敗しました。ページを再読み込みしてください。';
}

fetch('../data/jpx_master.json')
  .then(response => response.json())
  .then(result => {
    stocks = result.stocks.filter(stock => validCode.test(stock.code) && typeof stock.name === 'string');
    title();
    watchlist.updateSelection();
    input.dispatchEvent(new Event('input'));
  })
  .catch(() => { message.textContent = '銘柄名検索を読み込めませんでした。銘柄コードで検索できます。'; });
