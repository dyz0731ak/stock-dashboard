"""Cache genuine daily OHLC separately: the browser loads one instrument/range on click."""
import calendar
import datetime as dt
import json
import math
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

from market_clock import JST, parse_time
from market_http import get
from market_index_specs import MARKET_INDICES
from safe_save import _load_existing, _write_json_atomic

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'market_history'
PERIODS = (1,3,6,12,36)


def months_before(day, months):
    year, month0 = divmod(day.year*12+day.month-1-months,12)
    return dt.date(year,month0+1,min(day.day,calendar.monthrange(year,month0+1)[1]))


def parse_bars(result, spec, now):
    meta = result['meta']
    allowed = {'JPY=X','USDJPY=X'} if spec['id']=='usdjpy' else {spec['ticker']}
    if meta.get('symbol') not in allowed or meta.get('instrumentType')!=spec['instrument_type']:
        raise ValueError('Unexpected symbol or instrument type')
    zone = ZoneInfo(meta['exchangeTimezoneName'])
    raw = result['indicators']['quote'][0]
    bars = {}
    for i, stamp in enumerate(result['timestamp']):
        if stamp>now.timestamp()+300:
            continue
        try:
            o,h,l,c = [float(raw[key][i]) for key in ('open','high','low','close')]
            if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or l>min(o,c) or h<max(o,c) or h<l:
                continue
        except (TypeError,ValueError,IndexError):
            continue
        day = dt.datetime.fromtimestamp(stamp,zone).date().isoformat()
        bars[day] = dict(t=day,o=round(o,5),h=round(h,5),l=round(l,5),c=round(c,5))
    rows = sorted(bars.values(),key=lambda b:b['t'])
    if len(rows)<200 or (now.date()-dt.date.fromisoformat(rows[-1]['t'])).days>5:
        raise ValueError('Insufficient or outdated OHLC history')
    return rows


def collect(spec):
    now = dt.datetime.now(JST)
    longest = ROOT/f'{spec["id"]}-36M.json'
    old = _load_existing(str(longest)) or {}
    fetched = parse_time(old.get('fetched_at'))
    if fetched and dt.timedelta(0)<=now-fetched<dt.timedelta(hours=1):
        return dict(id=spec['id'],status='cached',count=len(old.get('bars',[])))
    errors = []
    start = dt.datetime.combine(months_before(now.date(),36)-dt.timedelta(days=7),dt.time(),JST)
    for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
        try:
            url = f'https://{host}/v8/finance/chart/{quote(spec["ticker"],safe="")}?period1={int(start.timestamp())}&period2={int(now.timestamp())}&interval=1d'
            chart = get(url).json()['chart']
            if chart.get('error'):
                raise ValueError(str(chart['error']))
            bars = parse_bars(chart['result'][0],spec,now)
            for months in PERIODS:
                cutoff = months_before(now.date(),months).isoformat()
                selected = [bar for bar in bars if bar['t']>=cutoff]
                out = dict(id=spec['id'],ticker=spec['ticker'],instrument_type=spec['instrument_type'],
                           label=spec['label'],unit=spec['unit'],period=f'{months}M',bars=selected,
                           fetched_at=now.isoformat(),as_of=bars[-1]['t'],source_label='Yahoo Finance',
                           source_url='https://finance.yahoo.com/quote/'+spec['ticker']+'/history/',
                           exchange_timezone=chart['result'][0]['meta']['exchangeTimezoneName'])
                _write_json_atomic(str(ROOT/f'{spec["id"]}-{months}M.json'),out)
            return dict(id=spec['id'],status='ok',count=len(bars),as_of=bars[-1]['t'],endpoint=host)
        except Exception as exc:
            errors.append(f'{host}: {exc}')
    # Leave successful history and its original timestamps intact on temporary failures.
    return dict(id=spec['id'],status='retained' if old.get('bars') else 'error',errors=errors)


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(collect,MARKET_INDICES[:-1]))
    print(json.dumps(dict(event='history_finished',results=results),ensure_ascii=False))
    return 1 if any(row['status']=='error' for row in results) else 0


if __name__=='__main__':
    raise SystemExit(main())
