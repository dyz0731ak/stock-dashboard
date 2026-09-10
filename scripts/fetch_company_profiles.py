"""Cache company descriptions independently of time-sensitive stock prices."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
JST = timezone(timedelta(hours=9))
CODE = re.compile(r'[0-9][0-9A-Z]{3}')


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def safe_url(value):
    parsed = urlparse(value or '')
    return value if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username else ''


def parse_profile(html, code):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text() if soup.title else ''
    if code not in title:
        raise ValueError('company_code_mismatch: response title does not identify requested company')

    def field(label):
        node = soup.find(string=lambda s: s and s.strip() == label)
        return node.parent.find_next_sibling() if node else None

    overview = field('概要')
    description = overview.get_text(' ', strip=True) if overview else ''
    if not 8 <= len(description) <= 1200:
        raise ValueError('company_overview_missing: expected company overview block')
    site = field('会社サイト')
    link = site.find('a', href=True) if site else None
    themes = field('関連テーマ')
    return {
        'description': description,
        'summary': description.split('。')[0].strip()[:64],
        'website': safe_url(link['href']) if link else '',
        'themes': list(dict.fromkeys(a.get_text(' ', strip=True) for a in themes.select('a[href^="/themes/"]')))[:8] if themes else [],
        'source': '株探・企業基本情報',
        'source_url': f'https://s.kabutan.jp/stocks/{code}/',
    }


def needs_refresh(profile, now):
    try:
        # A failed source retries after six hours; successful profiles are checked weekly.
        attempted = datetime.fromisoformat(profile['last_attempt_at'])
        interval = timedelta(hours=6) if profile.get('fetch_status') == 'error' else timedelta(days=7)
        return now - attempted >= interval
    except (KeyError, ValueError, TypeError):
        return True


def collect_one(code, stock, previous, now, session_get=requests.get):
    attempted = now.isoformat()
    url = f'https://s.kabutan.jp/stocks/{code}/'
    try:
        response = session_get(url, timeout=(5, 12), headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ja'})
        response.raise_for_status()
        profile = parse_profile(response.text, code)
        profile.update(code=code, name=stock.get('name') or code, sector=stock.get('sector') or '',
                       fetched_at=attempted, last_attempt_at=attempted, fetch_status='ok')
        print(json.dumps({'event': 'profile_saved', 'code': code, 'source_url': url}, ensure_ascii=False))
        return profile
    except Exception as exc:
        # Do not relabel old descriptions with a new successful-fetch timestamp.
        profile = dict(previous)
        profile.update(code=code, name=stock.get('name') or code, last_attempt_at=attempted,
                       fetch_status='error', fetch_error=f'{type(exc).__name__}: {exc}', source_url=url)
        print(json.dumps({'event': 'profile_failed', 'code': code, 'source_url': url,
                          'error': profile['fetch_error'], 'retained_fetched_at': profile.get('fetched_at')}, ensure_ascii=False))
        return profile


def main():
    now = datetime.now(JST)
    path = DATA / 'company_profiles.json'
    profiles = read(path).get('companies', {})
    stocks = {}
    for file in ('pts_ranking.json', 'japan_stocks.json'):
        for stock in read(DATA / file).get('all_stocks', []):
            code = str(stock.get('code', '')).upper()
            if CODE.fullmatch(code):
                stocks[code] = stock
    pending = {code: stock for code, stock in stocks.items() if needs_refresh(profiles.get(code, {}), now)}
    with ThreadPoolExecutor(max_workers=6) as executor:
        jobs = {executor.submit(collect_one, code, stock, profiles.get(code, {}), now): code for code, stock in pending.items()}
        for future in as_completed(jobs):
            profiles[jobs[future]] = future.result()
    # Editorial one-liners are separate from fetched cache so scheduled runs preserve them.
    overrides = read(ROOT / 'scripts/company_summaries.json')
    for code, profile in profiles.items():
        editorial = overrides.get(code, {})
        if editorial and editorial.get('based_on_description') == profile.get('description'):
            profile['summary'] = editorial['summary']
    result = {'checked_at': now.isoformat(), 'companies': profiles}
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)
    print(json.dumps({'event': 'profiles_finished', 'ranking_companies': len(stocks),
                      'attempted': len(pending), 'available': sum(bool(profiles.get(c, {}).get('description')) for c in stocks)}))


if __name__ == '__main__':
    main()
