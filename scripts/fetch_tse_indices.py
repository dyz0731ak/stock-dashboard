"""JPX's three whole-market segment indices, not selected-stock substitutes."""
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

import requests

from market_clock import JST, parse_time, session_valid_until
from market_index_specs import TSE_INDICES
from safe_save import safe_save, mark_failed
from fetch_market_indices import number, quote_time

SOURCE = 'https://www.jpx.co.jp/markets/indices/realvalues/index.html'
BASE = 'https://www.jpx.co.jp/market/indices/'


def parse_jpx(payload, timestamp, now):
    stamp = dt.datetime.strptime(timestamp.strip(), '%Y%m%d%H%M').replace(tzinfo=JST)
    quote_time(stamp.isoformat(), now, dt.timedelta(days=14))
    until = session_valid_until(stamp.date().isoformat(), 'tse', now.isoformat(), stamp.isoformat(), now)
    if parse_time(until) < now:
        raise ValueError('JPX snapshot is outside its valid trading session')
    rows = payload.get('TseMarketType', {})
    items, failures = [], []
    for spec in TSE_INDICES:
        try:
            row = rows[spec['ticker']]
            if row.get('marketName') != spec['label']:
                raise ValueError('index name does not match the full-market index')
            price, change, pct = [number(row[key].replace(',', '')) for key in
                                  ('currentPrice', 'previousDayComparison', 'previousDayRatio')]
            if price <= 0 or price-change <= 0:
                raise ValueError('invalid index price')
            if abs(pct - change/(price-change)*100) > .02:
                raise ValueError('inconsistent daily change')
            items.append(dict(spec, price=price, prev_close=round(price-change, 2), change=change, pct=pct,
                              chart=[], price_date=stamp.date().isoformat(), as_of=stamp.isoformat(),
                              fetched_at=now.isoformat(), valid_until=until,
                              source_label='JPX / QUICK', source_url=SOURCE))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            failures.append(dict(id=spec['id'], error=str(exc)))
    return items, failures


def download(filename):
    response = requests.get(BASE+filename, timeout=15, headers={'Cache-Control':'no-cache'})
    response.raise_for_status()
    return response.content.decode('utf-8-sig')


def main():
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            payload, timestamp = list(pool.map(download, ['indices_stock_price3.txt', 'indices_stock_price3.time.txt']))
        now = dt.datetime.now(JST)
        items, failures = parse_jpx(json.loads(payload), timestamp, now)
        out = dict(items=items, failures=failures, source='JPX / QUICK',
                   fetch_status='partial' if failures else 'ok',
                   fetch_warning=f'3指数中{len(items)}指数取得' if failures else None,
                   updated_at=now.isoformat())
        saved = safe_save('data/tse_indices.json', out, lambda data: len(data['items']), label='東証市場別指数')
        print(json.dumps(dict(saved=saved, count=len(items)), ensure_ascii=False))
        return 0 if saved else 1
    except Exception as exc:
        mark_failed('data/tse_indices.json', str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
