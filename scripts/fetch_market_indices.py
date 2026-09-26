"""Fetch cash indices, USD/JPY and XAU spot; never substitute futures."""
import datetime as dt
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import pandas as pd
from market_http import get
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

from market_clock import JST, parse_time, session_valid_until
from market_index_specs import MARKET_INDICES
from safe_save import safe_save, _load_existing


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('non-finite price')
    return value


def quote_time(value, now, max_age):
    stamp = parse_time(value)
    if not stamp or not -dt.timedelta(minutes=5) <= now - stamp <= max_age:
        raise ValueError('source timestamp is missing, stale or in the future')
    return stamp


def parse_yahoo(spec, history, metadata, now):
    symbol = metadata.get('symbol')
    aliases = {'JPY=X': {'JPY=X', 'USDJPY=X'}}
    if symbol not in aliases.get(spec['ticker'], {spec['ticker']}):
        raise ValueError('unexpected symbol; refuse an index substitute')
    if metadata.get('instrumentType') != spec['instrument_type']:
        raise ValueError('unexpected instrument type; cash/FX quotes only')
    raw_time = metadata['regularMarketTime']
    if hasattr(raw_time, 'isoformat'):
        raw_time = raw_time.isoformat()
    elif isinstance(raw_time, (int, float)):
        raw_time = dt.datetime.fromtimestamp(raw_time, dt.timezone.utc).isoformat()
    stamp = quote_time(raw_time, now, dt.timedelta(days=10 if spec['id']=='nk225' else 4))
    zone = ZoneInfo(metadata['exchangeTimezoneName'])
    market_day = stamp.astimezone(zone).date().isoformat()
    current = number(metadata['regularMarketPrice'])
    if current <= 0:
        raise ValueError('non-positive quote')
    chart = []
    for timestamp, row in history.iterrows():
        try:
            close = number(row['Close'])
        except (ValueError, TypeError):
            continue
        day = timestamp.strftime('%Y-%m-%d')
        if close > 0 and day <= market_day:
            chart.append(dict(t=day, c=round(close, 4)))
    previous = [point for point in chart if point['t'] < market_day]
    if not previous:
        raise ValueError('previous trading day close unavailable')
    prev_close = previous[-1]['c']
    # The current quote is a real observation, not a fabricated OHLC bar.
    chart = previous + [dict(t=market_day, c=round(current, 4))]
    valid_until = min(now + dt.timedelta(hours=8), stamp + dt.timedelta(days=4)).isoformat()
    if spec['id'] == 'nk225':
        valid_until = session_valid_until(market_day, 'tse', now.isoformat(), stamp.isoformat(), now)
        if parse_time(valid_until) < now:
            raise ValueError('Nikkei quote is outside its valid session')
    return dict(spec, price=round(current, 4), prev_close=prev_close,
                change=round(current-prev_close, 4), pct=round((current/prev_close-1)*100, 3),
                chart=chart[-140:], price_date=market_day, as_of=stamp.isoformat(),
                fetched_at=now.isoformat(), valid_until=valid_until,
                source_label='Yahoo Finance', source_url='https://finance.yahoo.com/quote/'+spec['ticker']+'/')


def parse_gold(payload, now):
    if payload.get('symbol') != 'XAU' or payload.get('currency') != 'USD':
        raise ValueError('expected USD gold spot quote')
    max_age = dt.timedelta(hours=72 if now.weekday() in (5, 6) or (now.weekday()==0 and now.hour<9) else 3)
    stamp = quote_time(payload.get('updatedAt'), now, max_age)
    price = number(payload['price'])
    if price <= 0:
        raise ValueError('non-positive gold quote')
    # The free spot endpoint has no previous close/history; leave them unknown.
    return dict(MARKET_INDICES[-1], price=price, prev_close=None, change=None, pct=None,
                chart=[], price_date=stamp.astimezone(JST).date().isoformat(),
                as_of=stamp.isoformat(), fetched_at=now.isoformat(),
                valid_until=min(now+dt.timedelta(hours=8), stamp+max_age).isoformat(),
                source_label='Gold API', source_url='https://gold-api.com/')


def raw_yahoo(spec):
    errors = []
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        try:
            url = f'https://{host}/v8/finance/chart/{quote(spec["ticker"], safe="")}?range=1mo&interval=1d'
            payload = get(url).json()['chart']
            if payload.get('error'):
                raise ValueError(str(payload['error']))
            result = payload['result'][0]
            meta = result['meta']
            rows = result['indicators']['quote'][0]
            history = pd.DataFrame(rows, index=pd.to_datetime(result['timestamp'], unit='s', utc=True).tz_convert(meta['exchangeTimezoneName']))
            history = history.rename(columns={key:key.capitalize() for key in rows})
            item = parse_yahoo(spec, history, meta, dt.datetime.now(JST))
            item['source_endpoint'] = host
            return item
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as exc:
            errors.append(f'{host}: {exc}')
    # Independent library path supports both epoch and pandas Timestamp metadata.
    try:
        ticker = yf.Ticker(spec['ticker'])
        history = ticker.history(period='1mo', interval='1d', auto_adjust=False, timeout=8)
        return parse_yahoo(spec, history, ticker.history_metadata, dt.datetime.now(JST))
    except Exception as exc:
        raise ValueError('; '.join(errors)+f'; yfinance: {exc}') from exc


def fetch_one(spec):
    try:
        if spec['id'] == 'gold':
            item = parse_gold(get('https://api.gold-api.com/price/XAU').json(), dt.datetime.now(JST))
        else:
            item = raw_yahoo(spec)
        print(json.dumps(dict(event='quote_ok', id=spec['id'], price=item['price'], as_of=item['as_of'],
                              endpoint=item.get('source_endpoint')), ensure_ascii=False), file=sys.stderr)
        return item, None
    except Exception as exc:
        print(f"{spec['ticker']}: {exc}", file=sys.stderr)
        return None, dict(id=spec['id'], error=str(exc))


def merge_cached(collected, previous, now):
    items, failures = [], []
    for spec, (item, error) in zip(MARKET_INDICES, collected):
        if item:
            items.append(item)
            continue
        failures.append(error)
        old = next((row for row in previous.get('items', []) if all(row.get(k)==spec[k] for k in ('id','ticker','instrument_type'))), None)
        if not old:
            continue
        fetched = parse_time(old.get('fetched_at'))
        if not fetched or not -dt.timedelta(minutes=5) <= now-fetched <= dt.timedelta(hours=24):
            continue
        cached = dict(old, cache_status='previous', cache_until=(fetched+dt.timedelta(hours=24)).isoformat(),
                      last_attempt_at=now.isoformat(), fetch_error=error['error'])
        items.append(cached)
    return items, failures


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        collected = list(pool.map(fetch_one, MARKET_INDICES))
    previous = _load_existing('data/market_indices.json') or {}
    items, failures = merge_cached(collected, previous, dt.datetime.now(JST))
    out = dict(items=items, failures=failures, source='Yahoo Finance / Gold API',
               fetch_status='partial' if failures else 'ok',
               fetch_warning=f'取得失敗{len(failures)}指標。取得済みの実値は基準時刻付きで保持' if failures else None,
               updated_at=dt.datetime.now(JST).isoformat())
    saved = safe_save('data/market_indices.json', out, lambda data: len(data['items']), label='主要マーケット指標')
    print(json.dumps(dict(saved=saved, count=len(items))))
    return 0 if saved else 1


if __name__ == '__main__':
    raise SystemExit(main())
