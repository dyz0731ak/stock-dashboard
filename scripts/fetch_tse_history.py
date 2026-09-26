"""Actual TSE segment OHLC: daily (3M), weekly (1Y), monthly (3Y).

Long-range source bars are extended only with complete groups of real daily
OHLC. Never turn closing prices or a different index into candlesticks.
"""
import datetime as dt
import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from fetch_market_history import ROOT, PERIODS, months_before
from market_clock import JST, business_day, market_context, parse_time
from market_http import get
from market_index_specs import TSE_INDICES
from safe_save import _load_existing, _write_json_atomic

BASE = 'https://finance.stockweather.co.jp'
CODES = {'tse-prime': '0500', 'tse-standard': '0501', 'tse-growth': '0502'}


def parse_bars(payload, now):
    bars = {}
    for raw in payload['ohlc_data']:
        if len(raw) != 5 or any(v is None for v in raw):
            raise ValueError('Missing OHLC')
        stamp, o, h, l, c = map(float, raw)
        if not all(math.isfinite(v) for v in (stamp, o, h, l, c)) or min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c):
            raise ValueError('Invalid OHLC range')
        day = dt.datetime.fromtimestamp(stamp/1000, JST).date()
        if day>now.date():
            raise ValueError('Future OHLC date')
        bar = dict(t=day.isoformat(),o=o,h=h,l=l,c=c)
        if bar['t'] in bars and bars[bar['t']] != bar:
            raise ValueError('Conflicting duplicate OHLC')
        bars[bar['t']] = bar
    return sorted(bars.values(),key=lambda b:b['t'])


def bucket(day, interval):
    return day-dt.timedelta(days=day.weekday()) if interval=='1wk' else day.replace(day=1)


def extend_bars(old, daily, interval):
    """Aggregate only buckets containing every trading day's actual OHLC."""
    groups = defaultdict(list)
    for row in daily:
        groups[bucket(dt.date.fromisoformat(row['t']),interval)].append(row)
    merged = {row['t']:row for row in old}
    last_day = dt.date.fromisoformat(daily[-1]['t'])
    for start, rows in groups.items():
        end = start+dt.timedelta(days=7) if interval=='1wk' else months_before(start,-1)
        end = min(end,last_day+dt.timedelta(days=1))
        expected = set()
        day = start
        while day<end:
            if business_day(day): expected.add(day.isoformat())
            day += dt.timedelta(days=1)
        if {r['t'] for r in rows} != expected:
            continue  # Do not use a partial first bucket or fill missing sessions.
        merged[start.isoformat()] = dict(t=start.isoformat(),o=rows[0]['o'],
                                        h=max(r['h'] for r in rows),l=min(r['l'] for r in rows),c=rows[-1]['c'])
    result = sorted(merged.values(),key=lambda r:r['t'])
    if not result or result[-1]['t'] != bucket(last_day,interval).isoformat() or result[-1]['c'] != daily[-1]['c']:
        raise ValueError('Long-range bars do not reach the latest trading session')
    # Reject gaps between the older source history and the daily extension.
    dates = {r['t'] for r in result}
    day = dt.date.fromisoformat(result[0]['t'])
    while day<=bucket(last_day,interval):
        if day.isoformat() not in dates:
            raise ValueError('Missing historical period')
        day = day+dt.timedelta(days=7) if interval=='1wk' else months_before(day,-1)
    return result


def collect(spec, snapshot, now):
    old = _load_existing(str(ROOT/f'{spec["id"]}-36M.json')) or {}
    fetched = parse_time(old.get('fetched_at'))
    if fetched and dt.timedelta(0)<=now-fetched<dt.timedelta(hours=1) and all((ROOT/f'{spec["id"]}-{months}M.json').exists() for months in PERIODS):
        return dict(id=spec['id'],status='cached')
    try:
        code = CODES[spec['id']]
        query = f'cntcode=jp&skubun=0&stkcode={code}&exctype=01'
        source = f'{BASE}/contents/marketdetail.aspx?{query}&contents=1'
        page = BeautifulSoup(get(source).content,'html.parser')
        if spec['label'] not in [h.get_text(strip=True) for h in page.select('h2')]:
            raise ValueError('Source index name mismatch')
        series = [parse_bars(get(f'{BASE}/ashx/histrorycalHighchartLarge.ashx?{query}&c={c}').json(),now) for c in (1,3,4)]
        daily = series[0]
        if len(daily)<40 or daily[-1]['t']!=market_context('tse',now)['session_date']:
            raise ValueError('Outdated or insufficient daily history')
        # Independently verify the final daily bar against the JPX index itself.
        row = snapshot['TseMarketType'][spec['ticker']]
        if row['marketName'] != spec['label']:
            raise ValueError('JPX index mismatch')
        if market_context('tse',now)['state'] in ('closed','holiday','preopen'):
            for k, field in [('o','openingPrice'),('h','highPrice'),('l','lowPrice'),('c','currentPrice')]:
                if abs(daily[-1][k]-float(row[field].replace(',','')))>0.02:
                    raise ValueError('OHLC differs from JPX snapshot')
        weekly, monthly = extend_bars(series[1],daily,'1wk'), extend_bars(series[2],daily,'1mo')
        outputs = []
        for months in PERIODS:
            interval, all_bars = ('1d',daily) if months<=3 else ('1wk',weekly) if months<=12 else ('1mo',monthly)
            cutoff = months_before(now.date(),months)
            if interval!='1d': cutoff=bucket(cutoff,interval)
            bars = [b for b in all_bars if b['t']>=cutoff.isoformat()]
            if not bars or (dt.date.fromisoformat(bars[0]['t'])-cutoff).days>7:
                raise ValueError('Insufficient requested period coverage')
            out = dict(id=spec['id'],ticker=spec['ticker'],label=spec['label'],instrument_type='INDEX',
                       unit='pt',period=f'{months}M',interval=interval,bars=bars,as_of=daily[-1]['t'],
                       fetched_at=now.isoformat(),exchange_timezone='Asia/Tokyo',source_label='StockWeather / JPX照合',
                       source_url=source,note='1・3ヶ月は日足、6ヶ月・1年は週足、3年は月足。長期足の直近部分は取得済みの日足を集計。週・月の途中の足は未確定です。')
            outputs.append((ROOT/f'{spec["id"]}-{months}M.json',out))
        for path, out in outputs:
            _write_json_atomic(str(path),out)
        return dict(id=spec['id'],status='ok',as_of=daily[-1]['t'],daily=len(daily),weekly=len(weekly),monthly=len(monthly))
    except Exception as exc:
        return dict(id=spec['id'],status='retained' if old.get('bars') else 'error',error=str(exc))


def main():
    now = dt.datetime.now(JST)
    try:
        response = get('https://www.jpx.co.jp/market/indices/indices_stock_price3.txt')
        snapshot = json.loads(response.content.decode('utf-8-sig'))
    except Exception as exc:
        print(json.dumps(dict(event='tse_history_failed',error=str(exc)),ensure_ascii=False))
        return 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda spec:collect(spec,snapshot,now),TSE_INDICES))
    print(json.dumps(dict(event='tse_history_finished',results=results),ensure_ascii=False))
    return 1 if any(r['status'] in ('error','retained') for r in results) else 0


if __name__=='__main__':
    raise SystemExit(main())
