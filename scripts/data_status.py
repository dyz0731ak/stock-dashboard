"""Shared SSG, collection and health semantics. Fetch time is never market time."""
import datetime as dt
import os
from market_clock import JST, parse_time, market_context, session_valid_until

TTL = {'futures.json':8, 'japan_stocks.json':1, 'pts_ranking.json':1,
       'market_news.json':12, 'nikkei225.json':12, 'themes.json':8,
       'earnings_flash.json':36, 'volume_stocks.json':36}

def stamp_data(path, data, now=None):
    now = now or dt.datetime.now(JST)
    filename = os.path.basename(path)
    fetched = parse_time(data.get('fetched_at') or data.get('updated_at'))
    if not fetched:
        return
    data['valid_until'] = (fetched + dt.timedelta(hours=TTL.get(filename, 12))).isoformat()
    if filename in ('japan_stocks.json', 'pts_ranking.json') and not data.get('is_fallback'):
        market = 'pts' if filename == 'pts_ranking.json' else 'tse'
        data['market'] = market
        context = market_context(market, now)
        data['market_state'] = context['state']
        if data.get('session_date'):
            data['valid_until'] = session_valid_until(data['session_date'], market,
                fetched.isoformat(), data.get('as_of') or data.get('prices_fetched_at'), now)
        else:
            data['fetch_status'] = 'stale'
            data['fetch_error'] = 'ランキングの取引日を確認できません'
    elif filename in ('nikkei225.json', 'themes.json'):
        rows = data.get('items', []) if filename == 'nikkei225.json' else data.get('themes', [])
        expected = market_context('tse', now)['session_date']
        dated = [row for row in rows if row.get('price_date') == expected]
        if len(dated) != len(rows):
            data['fetch_status'] = 'partial' if dated else 'stale'
            data['fetch_warning'] = f'直近営業日{expected}の値がある{len(dated)}/{len(rows)}件のみ表示'
            data['fetch_error'] = None if dated else f'取得元に{expected}の有効株価がありません'
            data['items' if filename == 'nikkei225.json' else 'themes'] = dated
        if dated:
            data['data_date'] = expected
            context = market_context('tse', now)
            if context['state'] != 'open':
                data['valid_until'] = session_valid_until(expected, 'tse', fetched.isoformat(), now=now)


def is_fresh(data, max_hours=12, now=None):
    now = now or dt.datetime.now(JST)
    if not data or data.get('fetch_status') in ('stale', 'error'):
        return False
    fetched = parse_time(data.get('fetched_at') or data.get('updated_at'))
    if not fetched or fetched > now + dt.timedelta(minutes=5):
        return False
    until = parse_time(data.get('valid_until'))
    if data.get('valid_until') and not until:
        return False
    if until:
        return now <= until
    return now - fetched <= dt.timedelta(hours=max_hours)

def status_text(data, hours=12):
    if not data:
        return '未取得'
    label = '取得失敗・期限切れ' if not is_fresh(data, hours) else {
        'partial':'一部取得', 'fallback':'代替取得'}.get(data.get('fetch_status'), '取得済み')
    stamp = parse_time(data.get('fetched_at') or data.get('updated_at'))
    fetched = stamp.astimezone(JST).strftime('%m/%d %H:%M') if stamp else '不明'
    date = data.get('session_date') or data.get('data_date') or data.get('article_date')
    return f'{label} ｜ 最終取得 {fetched} JST' + (f' ｜ 対象日 {date}' if date else '')
