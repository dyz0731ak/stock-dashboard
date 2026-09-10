#!/usr/bin/env python3
"""
JPX公式の東証上場銘柄一覧を母集団に、yfinanceの日足を一括取得して
東証全市場の値上がり率上位30件を作成する。取得できない場合は
楽天証券の公開ランキング、kabutan.jp、日経225の順に切り替える。

出力 JSON 構造:
  updated_at        : ISO8601 (JST)
  all_stocks        : ストップ高 + 近高を change_pct 降順でマージ済みリスト
  stop_high_count   : S高フラグ件数
  near_stop_count   : 上昇率上位（S高以外）件数
  sector_analysis   : 業種別集計
  theme_keywords    : テーマキーワードリスト

各銘柄フィールド:
  code, name, market, price, stop_high_price, is_stop_high
  change_amount, change_pct, volume, sector
  description, industry, website   (yfinance info)
  chart: { dates, opens, highs, lows, closes, volumes } (約6ヶ月日足)
"""

import requests
from bs4 import BeautifulSoup
import json
import datetime
import re
import sys
import os
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save
try:
    from translate import load_cache, save_cache, enrich_with_translations
    HAS_TRANSLATE = True
except ImportError:
    HAS_TRANSLATE = False
    print("[警告] translate モジュール未検出: 翻訳スキップ", file=sys.stderr)

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    print("[警告] yfinance が未インストール: チャート・会社情報なし", file=sys.stderr)

# ─────────────── 設定 ───────────────
BASE_URL          = "https://kabutan.jp"
LIST_URL          = (BASE_URL
    + "/warning/?mode=2_1&market=0&capitalization=-1"
    + "&dispmode=normal&stc=&stm=0&page={page}")
DETAIL_URL        = BASE_URL + "/stock/?code={code}"

MAX_PAGES         = 20    # 最大走査ページ数
STOP_AFTER_NO_S   = 3     # 連続 N ページ S高なし → 打ち切り
TOP_NEAR_STOP     = 50    # S高以外の上昇率上位の保持件数
RAKUTEN_RANK_URL  = (
    "https://www.rakuten-sec.co.jp/smartphone/market/info/pagecontent"
    "?pid=600&rid=0&xid={market_id}"
)
RAKUTEN_MARKETS   = {
    0: "東証P",
    1: "東証S",
    2: "東証G",
}
RAKUTEN_GLOBAL_TOP = 10
TSE_GLOBAL_TOP     = 30
CHART_TRADING_DAYS = 130  # 約6か月分の営業日
JPX_LIST_URL       = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)
JPX_MARKETS = {
    "プライム（内国株式）": "東証P",
    "スタンダード（内国株式）": "東証S",
    "グロース（内国株式）": "東証G",
}

# チャート・会社情報を取得する対象（件数制限で Actions 時間を節約）
CHART_INFO_MAX_STOP_HIGH = 50   # S高全件
CHART_INFO_MAX_NEAR_STOP = 30   # 上昇率上位 N 件

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ═══════════════════════════════════════════
#  JPX公式銘柄一覧 × yfinance 一括株価
# ═══════════════════════════════════════════

JPX_LIST_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
MASTER_CACHE = "data/jpx_master.json"
FETCH_DIAGNOSTICS = []
BULK_METADATA = {}

def record_source(source, status, **details):
    event = {"source": source, "status": status, **details}
    FETCH_DIAGNOSTICS.append(event)
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr)

def discover_master_url(html):
    from urllib.parse import urljoin, urlparse
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select('a[href]'):
        url = urljoin(JPX_LIST_PAGE, link['href'])
        if urlparse(url).hostname == 'www.jpx.co.jp' and re.search(r'/data_j\.xlsx?(?:\?|$)', url):
            return url
    raise ValueError("JPX上場一覧ページに data_j.xls/xlsx がありません")

def parse_master(content):
    import io
    import pandas as pd
    frame = pd.read_excel(io.BytesIO(content), engine='openpyxl' if content[:2] == b'PK' else 'xlrd')
    stocks = []
    for _, row in frame.iterrows():
        market = str(row['市場・商品区分']).strip()
        if market not in JPX_MARKETS:
            continue
        code = str(row['コード']).removesuffix('.0').strip()
        if not re.fullmatch(r'[0-9][0-9A-Z]{3}', code):
            continue
        stocks.append({'code':code, 'name':unicodedata.normalize('NFKC', str(row['銘柄名'])),
                       'market':JPX_MARKETS[market], 'sector':str(row['33業種区分'])})
    if len(stocks) < 3000 or len({s['code'] for s in stocks}) != len(stocks):
        raise ValueError(f'JPX銘柄一覧の件数・重複が不正: {len(stocks)}')
    return stocks

def fetch_jpx_listed_stocks():
    from safe_save import _load_existing, _write_json_atomic
    from market_clock import parse_time, JST
    now = datetime.datetime.now(JST)
    cache = _load_existing(MASTER_CACHE) or {}
    cached_at = parse_time(cache.get('fetched_at'))
    if cached_at and (now - cached_at).total_seconds() < 86400 and len(cache.get('stocks', [])) >= 3000:
        return cache['stocks']
    url = JPX_LIST_PAGE
    try:
        page = SESSION.get(url, timeout=30)
        page.raise_for_status()
        url = discover_master_url(page.text)
        response = SESSION.get(url, timeout=45)
        response.raise_for_status()
        stocks = parse_master(response.content)
        _write_json_atomic(MASTER_CACHE, {'fetched_at':now.isoformat(), 'url':url, 'stocks':stocks})
        record_source('jpx_master', 'ok', url=url, count=len(stocks))
        return stocks
    except Exception as exc:
        record_source('jpx_master', 'error', url=url, error=str(exc), exception=type(exc).__name__)
        if cached_at and (now - cached_at).days < 40 and len(cache.get('stocks', [])) >= 3000:
            record_source('jpx_master', 'fallback', cached_at=cache['fetched_at'])
            return cache['stocks']
        return []


def _series_values(frame, column, tail=CHART_TRADING_DAYS):
    """DataFrame列をJSON向けの配列に整える。"""
    values = []
    for value in frame[column].tail(tail):
        values.append(round(float(value), 2) if value == value else None)
    return values


def fetch_tse_all_market():
    """
    JPX公式の全上場銘柄を母集団に、yfinance日足を一括取得して
    東証P/S/G横断の値上がり率上位30銘柄を算出する。
    """
    if not HAS_YFINANCE:
        return []
    master = fetch_jpx_listed_stocks()
    if not master:
        return []

    BULK_METADATA["prices_fetched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"  東証全市場を一括計算: {len(master)}銘柄", file=sys.stderr)
    by_code = {s["code"]: s for s in master}
    candidates = []
    chunk_size = 400
    for start in range(0, len(master), chunk_size):
        chunk = master[start:start + chunk_size]
        tickers = [f"{s['code']}.T" for s in chunk]
        try:
            data = yf.download(
                tickers,
                period="5d",
                interval="1d",
                group_by="ticker",
                threads=12,
                timeout=15,
                progress=False,
                auto_adjust=False,
            )
        except Exception as e:
            print(f"  一括株価 {start}件目で失敗: {e}", file=sys.stderr)
            continue

        for ticker in tickers:
            code = ticker[:-2]
            try:
                frame = data[ticker] if len(tickers) > 1 else data
                frame = frame.dropna(subset=["Close"])
                if len(frame) < 2:
                    continue
                last = float(frame["Close"].iloc[-1])
                prev = float(frame["Close"].iloc[-2])
                if prev <= 0 or last <= 0:
                    continue
                # yfinance Close is split-adjusted. Keep the provider's comparable daily closes.
                change = last - prev
                meta = by_code[code]
                chart_frame = frame.tail(CHART_TRADING_DAYS)
                candidates.append({
                    **meta,
                    "price": round(last, 2),
                    "stop_high_price": (
                        round(last, 2) if is_price_limit_high(last, change) else None
                    ),
                    "is_stop_high": is_price_limit_high(last, change),
                    "change_amount": round(change, 2),
                    "change_pct": round(change / prev * 100, 3),
                    "volume": (
                        int(frame["Volume"].iloc[-1])
                        if frame["Volume"].iloc[-1] == frame["Volume"].iloc[-1]
                        else None
                    ),
                    "description": None,
                    "industry": None,
                    "website": None,
                    "price_date": frame.index[-1].strftime("%Y-%m-%d"),
                    "chart": {
                        "dates": [d.strftime("%Y-%m-%d") for d in chart_frame.index],
                        "opens": _series_values(chart_frame, "Open"),
                        "highs": _series_values(chart_frame, "High"),
                        "lows": _series_values(chart_frame, "Low"),
                        "closes": _series_values(chart_frame, "Close"),
                        "volumes": [
                            int(v) if v == v else None
                            for v in chart_frame["Volume"]
                        ],
                    },
                })
            except Exception as exc:
                record_source('yfinance_row', 'error', code=code, error=str(exc), exception=type(exc).__name__)
                continue
        print(
            f"    一括株価 {min(start + chunk_size, len(master))}/{len(master)}",
            file=sys.stderr,
        )

    if len(candidates) < 2500:
        print(f"  東証全市場の有効株価が不足: {len(candidates)}件", file=sys.stderr)
        return []

    # 売買停止・上場廃止などの古い最終値をランキングへ混ぜない。
    from market_clock import market_context
    latest_date = market_context()['session_date']
    current = [s for s in candidates if s["price_date"] == latest_date]
    coverage = len(current) / len(master)
    BULK_METADATA.update(universe_count=len(master), quoted_count=len(current), coverage=round(coverage, 4))
    record_source('yfinance_bulk', 'ok' if coverage == 1 else 'partial', **BULK_METADATA, session_date=latest_date)
    if coverage < .95:
        return []
    current = [s for s in current if s["change_pct"] > 0]
    current.sort(key=change_pct_float, reverse=True)
    print(
        f"  東証全市場 {latest_date}: 有効{len(current)}件 / 上位{TSE_GLOBAL_TOP}件",
        file=sys.stderr,
    )
    return current[:TSE_GLOBAL_TOP]


# ═══════════════════════════════════════════
#  楽天証券 公開ランキング（東証P/S/G）
# ═══════════════════════════════════════════

def parse_number(text):
    """カンマ・符号・%付きの表示値を float に変換"""
    cleaned = str(text or "").replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def daily_price_limit(previous_close):
    """東証の基準値段別・通常の制限値幅を返す（円）"""
    bands = [
        (100, 30), (200, 50), (500, 80), (700, 100), (1_000, 150),
        (1_500, 300), (2_000, 400), (3_000, 500), (5_000, 700),
        (7_000, 1_000), (10_000, 1_500), (15_000, 3_000),
        (20_000, 4_000), (30_000, 5_000), (50_000, 7_000),
        (70_000, 10_000), (100_000, 15_000), (150_000, 30_000),
        (200_000, 40_000), (300_000, 50_000), (500_000, 70_000),
        (700_000, 100_000), (1_000_000, 150_000),
        (1_500_000, 300_000), (2_000_000, 400_000),
        (3_000_000, 500_000), (5_000_000, 700_000),
        (7_000_000, 1_000_000), (10_000_000, 1_500_000),
        (15_000_000, 3_000_000), (20_000_000, 4_000_000),
        (30_000_000, 5_000_000), (50_000_000, 7_000_000),
    ]
    if previous_close is None or previous_close < 0:
        return None
    for upper, limit in bands:
        if previous_close < upper:
            return limit
    return 10_000_000


def is_price_limit_high(price, change_amount):
    """現在値と前日比から通常のストップ高到達を推定"""
    if price is None or change_amount is None or change_amount <= 0:
        return False
    previous_close = price - change_amount
    limit = daily_price_limit(previous_close)
    return limit is not None and abs(change_amount - limit) < 0.01


def parse_rakuten_ranking(html, expected_market):
    """楽天証券のランキングHTMLから銘柄行を抽出"""
    soup = BeautifulSoup(html, "html.parser")
    stocks = []
    for row in soup.select(".rankingBox li"):
        name_el = row.select_one(".name")
        code_el = row.select_one(".code")
        price_el = row.select_one(".price")
        pct_el = row.select_one(".percent")
        if not all((name_el, code_el, price_el, pct_el)):
            continue

        price = parse_number(price_el.get_text(strip=True))
        change_el = row.select_one(".change")
        change_amount = parse_number(change_el.get_text(strip=True)) if change_el else None
        change_pct = parse_number(pct_el.get_text(strip=True))
        code = code_el.get_text(strip=True)
        market_el = row.select_one(".market")
        market = market_el.get_text(strip=True) if market_el else expected_market
        if not code or price is None or change_pct is None:
            continue

        stocks.append({
            "code": code,
            "name": name_el.get_text(strip=True),
            "market": market,
            "price": price,
            "stop_high_price": price if is_price_limit_high(price, change_amount) else None,
            "is_stop_high": is_price_limit_high(price, change_amount),
            "change_amount": change_amount,
            "change_pct": change_pct,
            "volume": None,
            "sector": None,
            "description": None,
            "industry": None,
            "website": None,
            "chart": None,
        })
    return stocks


def parse_rakuten_timestamp(html):
    from market_clock import JST
    soup = BeautifulSoup(html, 'html.parser')
    box = soup.select_one('.rankingBox')
    text = box.get_text(' ', strip=True) if box else ''
    japanese = re.search(r'(?<!\d)(\d{2,4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})(?!\d)', text)
    if japanese:
        y,m,d,h,minute = map(int,japanese.groups())
        return datetime.datetime(2000+y if y<100 else y,m,d,h,minute,tzinfo=JST)
    english = re.search(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} \d{1,2} \d{2}:\d{2}:\d{2} GMT \d{4}',text)
    if english:
        return datetime.datetime.strptime(english[0], '%a %b %d %H:%M:%S GMT %Y').replace(tzinfo=datetime.timezone.utc)
    raise ValueError('楽天証券ランキングの基準日時がありません')


def fetch_rakuten_all_market():
    """
    東証P/S/Gの上位10件を取得して統合する。
    全市場上位10件は、各市場上位10件の和集合内に必ず含まれる。
    """
    combined = []
    for market_id, market_name in RAKUTEN_MARKETS.items():
        url = RAKUTEN_RANK_URL.format(market_id=market_id)
        try:
            resp = SESSION.get(url, timeout=20)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            rows = parse_rakuten_ranking(resp.text, market_name)
            from market_clock import market_context
            checked = parse_rakuten_timestamp(resp.text)
            from market_clock import JST
            expected = market_context()['session_date']
            if checked.astimezone(JST).date().isoformat() < expected:
                raise ValueError(f'楽天証券の日時が古い: {checked.isoformat()}')
            for row in rows:
                row['price_date'] = expected
                row['source_checked_at'] = checked.isoformat()
        except Exception as e:
            record_source('rakuten', 'error', market=market_name, url=url, error=str(e), exception=type(e).__name__)
            return []
        if len(rows) < RAKUTEN_GLOBAL_TOP:
            print(f"  楽天証券 {market_name}: {len(rows)}件（必要件数未満）", file=sys.stderr)
            return []
        print(f"  楽天証券 {market_name}: {len(rows)}件", file=sys.stderr)
        combined.extend(rows)

    unique = {s["code"]: s for s in combined}
    ranked = sorted(unique.values(), key=change_pct_float, reverse=True)
    return ranked[:RAKUTEN_GLOBAL_TOP]


# ═══════════════════════════════════════════
#  kabutan スクレイピング
# ═══════════════════════════════════════════

def get_total_pages(soup):
    pager = soup.find("div", class_="pagination")
    if not pager:
        return 1
    nums = [
        int(m.group(1))
        for a in pager.find_all("a")
        for m in [re.search(r"page=(\d+)", a.get("href", ""))]
        if m
    ]
    return max(nums) if nums else 1


def parse_table_rows(soup):
    """
    stock_table の行をパース
    確認済み列: [0]コード [1]銘柄名 [2]市場 [3]概要 [4]チャート
                [5]株価  [6]Sフラグ [7]前日比 [8]変化率% [9]出来高
    """
    table = soup.find("table", class_="stock_table")
    if not table:
        return []
    stocks = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all(["td", "th"])
        if len(cols) < 9:
            continue
        try:
            code_a = cols[0].find("a")
            code   = code_a.get_text(strip=True) if code_a else cols[0].get_text(strip=True)
            if not re.match(r"^\d{4}$", code):
                continue

            name   = cols[1].get_text(strip=True)
            market = cols[2].get_text(strip=True)

            price_raw = cols[5].get_text(strip=True).replace(",", "")
            price     = float(price_raw) if price_raw not in ("", "-") else None

            flag_span   = cols[6].find("span", class_="up")
            is_stop_high = bool(flag_span and flag_span.get_text(strip=True) == "S")

            chg_span     = cols[7].find("span") or cols[7]
            change_amount = chg_span.get_text(strip=True).replace(",", "")

            change_pct = cols[8].get_text(strip=True).replace("%", "").strip()

            vol_raw = cols[9].get_text(strip=True).replace(",", "") if len(cols) > 9 else ""
            volume  = int(vol_raw) if vol_raw.isdigit() else None

            stocks.append({
                "code": code, "name": name, "market": market,
                "price": price, "stop_high_price": price,
                "is_stop_high": is_stop_high,
                "change_amount": change_amount, "change_pct": change_pct,
                "volume": volume,
                "sector": None, "description": None,
                "industry": None, "website": None,
                "chart": None,
            })
        except Exception as e:
            print(f"    行パースエラー: {e}", file=sys.stderr)
    return stocks


def fetch_sector_kabutan(code):
    """kabutan 個別ページから業種を取得"""
    try:
        resp = SESSION.get(DETAIL_URL.format(code=code), timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for th in soup.find_all("th"):
            if th.get_text(strip=True) == "業種":
                td = th.find_next_sibling("td")
                if td:
                    return code, td.get_text(strip=True)
        return code, "不明"
    except Exception:
        return code, "不明"


def fetch_stop_high_pages():
    """変化率上位ページを走査して S高 + 上昇率上位銘柄を収集"""
    all_stop_high, all_near_stop = [], []
    no_s_streak, total_pages = 0, None

    print(f"  ストップ高ページ走査（最大{MAX_PAGES}ページ）...", file=sys.stderr)
    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            time.sleep(0.4)
        try:
            resp = SESSION.get(LIST_URL.format(page=page), timeout=20)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  page {page} 取得失敗: {e}", file=sys.stderr)
            continue

        if total_pages is None:
            total_pages = get_total_pages(soup)
            print(f"  総ページ数: {total_pages}（上位{MAX_PAGES}ページ走査）", file=sys.stderr)

        rows = parse_table_rows(soup)
        s_rows = [r for r in rows if r["is_stop_high"]]
        n_rows = [r for r in rows if not r["is_stop_high"]]

        all_stop_high.extend(s_rows)
        if len(all_near_stop) < TOP_NEAR_STOP:
            all_near_stop.extend(n_rows[: TOP_NEAR_STOP - len(all_near_stop)])

        print(f"  page {page}: 全{len(rows)}件 S高={len(s_rows)}件 "
              f"(累計S高={len(all_stop_high)}件)", file=sys.stderr)

        no_s_streak = 0 if s_rows else no_s_streak + 1
        if no_s_streak >= STOP_AFTER_NO_S:
            print(f"  → {STOP_AFTER_NO_S}ページ連続 S高なし → 打ち切り", file=sys.stderr)
            break

    return all_stop_high, all_near_stop


def enrich_sector_kabutan(stocks, max_workers=10):
    """kabutan 個別ページから業種を並列取得"""
    if not stocks:
        return stocks
    print(f"  kabutan 業種取得中（{len(stocks)}件, {max_workers}並列）...", file=sys.stderr)
    sector_map = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for code, sector in ex.map(
            lambda s: fetch_sector_kabutan(s["code"]), stocks
        ):
            sector_map[code] = sector
    for s in stocks:
        s["sector"] = sector_map.get(s["code"], "不明")
    return stocks


# ═══════════════════════════════════════════
#  yfinance チャート・会社情報
# ═══════════════════════════════════════════

def fetch_yfinance_data(code):
    """
    yfinance で {code}.T の 6ヶ月日足 + 会社情報を取得
    Returns: (code, chart_dict, info_dict)
    """
    if not HAS_YFINANCE:
        return code, None, {}

    ticker_sym = f"{code}.T"
    try:
        t = yf.Ticker(ticker_sym)

        # ── 6ヶ月日足 ──
        hist = t.history(period="6mo", interval="1d", auto_adjust=True, timeout=10)
        chart = None
        hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
        if not hist.empty:
            chart = {
                "dates":   [d.strftime("%Y-%m-%d") for d in hist.index],
                "opens":   [round(float(v), 2) if v == v else None
                            for v in hist["Open"]],
                "highs":   [round(float(v), 2) if v == v else None
                            for v in hist["High"]],
                "lows":    [round(float(v), 2) if v == v else None
                            for v in hist["Low"]],
                "closes":  [round(float(v), 1) if v == v else None
                            for v in hist["Close"]],
                "volumes": [int(v) if v == v else None
                            for v in hist["Volume"]],
            }

        # ── 会社情報 ──
        info = {}  # company metadata is optional; avoid 30 extra quote-summary requests
        company = {
            "description": (info.get("longBusinessSummary") or "")[:400],
            "industry":    info.get("industry") or "",
            "website":     info.get("website") or "",
        }

        return code, chart, company

    except Exception as e:
        print(f"    yfinance 失敗 {ticker_sym}: {e}", file=sys.stderr)
        return code, None, {}


def enrich_yfinance(stocks, max_workers=8, label=""):
    """並列 yfinance で chart + 会社情報を補完"""
    if not stocks or not HAS_YFINANCE:
        return stocks

    print(f"  yfinance 取得中（{label}{len(stocks)}件, {max_workers}並列）...",
          file=sys.stderr)

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_yfinance_data, s["code"]): s["code"] for s in stocks}
        done = 0
        for fut in as_completed(futures):
            try:
                code, chart, company = fut.result()
            except Exception as exc:
                record_source('chart_enrichment', 'error', code=futures[fut], error=str(exc))
                continue
            results[code] = (chart, company)
            done += 1
            if done % 10 == 0:
                print(f"    進捗 {done}/{len(stocks)}", file=sys.stderr)

    for s in stocks:
        chart, company = results.get(s["code"], (None, {}))
        if chart:
            s["chart"] = chart
        if company.get("description"):
            s["description"] = company["description"]
        if company.get("industry"):
            s["industry"] = company["industry"]
        if company.get("website"):
            s["website"] = company["website"]

    return stocks


# ═══════════════════════════════════════════
#  テーマキーワード抽出
# ═══════════════════════════════════════════

# 英語の業界キーワード（説明文検索用）
THEME_EN_WORDS = [
    ("AI", ["artificial intelligence", " ai ", "machine learning", "deep learning"]),
    ("半導体", ["semiconductor", "chip", "wafer", "fab"]),
    ("ドローン", ["drone", "unmanned aerial"]),
    ("EV・電池", ["electric vehicle", " ev ", "battery", "lithium"]),
    ("再生可能エネルギー", ["solar", "renewable energy", "wind power", "photovoltaic"]),
    ("ロボット", ["robot", "automation", "automated"]),
    ("クラウド・SaaS", ["cloud", "saas", "software as a service"]),
    ("サイバーセキュリティ", ["cybersecurity", "cyber security", "security software"]),
    ("バイオ・創薬", ["biotech", "pharmaceutical", "drug discovery", "clinical"]),
    ("フィンテック", ["fintech", "payment", "digital finance"]),
    ("IoT", ["internet of things", " iot "]),
    ("DX", ["digital transformation", " dx ", "digitalization"]),
    ("宇宙", ["space", "satellite", "rocket", "aerospace"]),
    ("量子コンピュータ", ["quantum", "quantum computing"]),
]


def extract_theme_keywords(stop_high_stocks, sector_analysis):
    """テーマキーワードを抽出"""
    keywords_score = {}

    # ── 業種名（S高業種ほど高スコア）──
    for i, (sector, info) in enumerate(sector_analysis.items()):
        score = info["count"] * 3 + max(0, 10 - i)
        keywords_score[sector] = keywords_score.get(sector, 0) + score

    # ── インダストリー名 ──
    for s in stop_high_stocks:
        ind = (s.get("industry") or "").strip()
        if ind and ind not in ("", "不明"):
            keywords_score[ind] = keywords_score.get(ind, 0) + 2

    # ── 説明文から英語テーマを検出 ──
    all_desc = " ".join(
        (s.get("description") or "").lower() for s in stop_high_stocks
    )
    for label, patterns in THEME_EN_WORDS:
        if any(p in all_desc for p in patterns):
            keywords_score[label] = keywords_score.get(label, 0) + 5

    # スコア上位 15 件を返す
    sorted_kw = sorted(keywords_score.items(), key=lambda x: -x[1])
    return [kw for kw, _ in sorted_kw[:15]]


# ═══════════════════════════════════════════
#  集計・メイン
# ═══════════════════════════════════════════

def aggregate_by_sector(stocks):
    sector_count = {}
    for s in stocks:
        sector = s.get("sector") or "不明"
        if sector not in sector_count:
            sector_count[sector] = {"count": 0, "codes": []}
        sector_count[sector]["count"] += 1
        sector_count[sector]["codes"].append(s["code"])
    return dict(sorted(sector_count.items(), key=lambda x: -x[1]["count"]))


def change_pct_float(s):
    """change_pct を float に変換（ソート用）"""
    try:
        return float(str(s.get("change_pct", "0")).replace("+", "").replace("%", ""))
    except ValueError:
        return 0.0


def load_nikkei225_fallback():
    """
    株探を取得できない環境向けの代替データ。
    日経225構成銘柄に範囲を限定し、全市場ランキングとは明確に区別する。
    """
    path = "data/nikkei225.json"
    try:
        with open(path, encoding="utf-8") as f:
            source = json.load(f)
    except Exception as e:
        print(f"[日本株] 日経225フォールバック読込失敗: {e}", file=sys.stderr)
        return None

    from market_clock import parse_time, JST
    timestamp = parse_time(source.get('updated_at'))
    if not source.get('data_date') or source.get('fetch_status') == 'stale' or not timestamp or (datetime.datetime.now(JST) - timestamp).total_seconds() > 12 * 3600:
        return None
    stocks = []
    for item in source.get("stocks", source.get("items", [])):
        price = item.get("price")
        prev = item.get("prev_close")
        pct = item.get("change_pct")
        if price is None or pct is None:
            continue
        change = (price - prev) if prev is not None else None
        stocks.append({
            "code": str(item.get("code") or "").replace(".T", ""),
            "name": item.get("name") or item.get("ticker") or "",
            "market": "東証",
            "price": price,
            "stop_high_price": None,
            "is_stop_high": False,
            "change_amount": round(change, 2) if change is not None else None,
            "change_pct": round(float(pct), 3),
            "volume": item.get("volume"),
            "sector": item.get("sector") or "不明",
            "description": None,
            "industry": None,
            "website": None,
            "chart": None,
        })

    stocks.sort(key=change_pct_float, reverse=True)
    if not stocks:
        return None

    return {
        "stocks": stocks[:50],
        "source_updated_at": source.get("updated_at"),
        "session_date": source.get("data_date"),
    }


KABUTAN_TSE_URL = 'https://s.kabutan.jp/warnings/price_increase/'

def parse_kabutan_tse(html):
    soup = BeautifulSoup(html, 'html.parser')
    stamp = re.search(r'株価：(\d{4})年(\d{2})月(\d{2})日\s+(\d{2}:\d{2})現在', soup.get_text(' ',strip=True))
    if not stamp:
        raise ValueError('株探の市場データ日時がありません')
    date = '-'.join(stamp.groups()[:3])
    as_of = f'{date}T{stamp[4]}:00+09:00'
    stocks=[]
    for row in soup.select('table tbody tr'):
        cells=row.find_all(['th','td'],recursive=False)
        if len(cells)<4:
            continue
        link=cells[0].find('a',href=re.compile(r'^/stocks/[0-9A-Z]+/'))
        if not link:
            continue
        code=re.search(r'/stocks/([0-9A-Z]+)/',link['href'])[1]
        market=next((span.get_text(strip=True) for span in link.find_all('span') if span.get_text(strip=True) in ('東P','東S','東G')),None)
        if not market:
            continue
        parts=list(cells[2].stripped_strings)
        price=parse_number(cells[1].get_text(strip=True))
        change=parse_number(parts[0]) if parts else None
        pct=parse_number(parts[1]) if len(parts)>1 else None
        if price is None or change is None or pct is None or pct<=0:
            raise ValueError(f'株探の価格行が不正: code={code}')
        name=link.find('abbr')
        name=name.get('title') if name and name.get('title') else link.find('p').get_text(strip=True)
        stocks.append({'code':code,'name':name,'market':{'東P':'東証P','東S':'東証S','東G':'東証G'}[market],
                       'price':price,'change_amount':change,'change_pct':pct,'price_date':date,
                       'source_checked_at':as_of,'is_stop_high':'Ｓ' in link.get_text(),
                       'volume':parse_number(cells[3].get_text(strip=True).replace('株','')), 'chart':None, 'sector':None})
    return date,as_of,stocks

def fetch_kabutan_tse():
    from market_clock import market_context
    expected=market_context()['session_date']
    combined={}
    dates=[]
    try:
        for page in range(1,5):
            response=SESSION.get(KABUTAN_TSE_URL,params={'page':page},timeout=15)
            response.raise_for_status()
            date,as_of,stocks=parse_kabutan_tse(response.text)
            if date!=expected:
                raise ValueError(f'株探の市場日が古い: expected={expected}, actual={date}, page={page}')
            dates.append(as_of)
            for stock in stocks: combined[stock['code']]=stock
            if len(combined)>=30: break
        if len(combined)<30:
            raise ValueError(f'株探の市場上位30件が不足: {len(combined)}')
        # Mixed market snapshots across pages should be explicit, never silently combined.
        if len(set(dates))!=1:
            raise ValueError(f'株探ページ間の基準時刻が不一致: {dates}')
        record_source('kabutan_mobile','ok',count=len(combined),as_of=min(dates),url=KABUTAN_TSE_URL)
        return sorted(combined.values(),key=change_pct_float,reverse=True)[:30]
    except Exception as exc:
        record_source('kabutan_mobile','error',error=str(exc),url=KABUTAN_TSE_URL)
        return []


def fetch_bulk_with_deadline():
    """A slow bulk source cannot consume the fallback's entire time budget."""
    import subprocess
    try:
        result = subprocess.run([sys.executable, __file__, '--bulk-only'],
                                stdout=subprocess.PIPE, text=True, timeout=280, check=True)
        payload = json.loads(result.stdout)
        BULK_METADATA.update(payload['metadata'])
        FETCH_DIAGNOSTICS.extend(payload['diagnostics'])
        return payload['stocks']
    except (subprocess.SubprocessError, ValueError, KeyError) as exc:
        record_source('yfinance_bulk', 'error', error=str(exc), exception=type(exc).__name__)
        return []


def main():
    print("[日本株] 取得開始...", file=sys.stderr)

    # 1. JPX公式の全銘柄を母集団に一括計算。失敗時は楽天、さらに株探へ切替。
    source_kind = "tse_bulk"
    if os.environ.get("FORCE_JP_FALLBACK") == "1":
        stop_high, near_stop = [], []
        print("[日本株] テスト指定により外部ランキング取得をスキップ", file=sys.stderr)
    else:
        all_market = [] if os.environ.get('FORCE_RAKUTEN') == '1' or os.environ.get('FORCE_KABUTAN') == '1' else fetch_bulk_with_deadline()
        if not all_market and os.environ.get('FORCE_RAKUTEN') != '1':
            source_kind = 'kabutan_mobile'
            all_market = fetch_kabutan_tse()
        if not all_market:
            source_kind = "rakuten"
            print("[日本株] 全銘柄一括計算失敗 → 楽天証券へ切替", file=sys.stderr)
            all_market = fetch_rakuten_all_market()
        stop_high = [s for s in all_market if s["is_stop_high"]]
        near_stop = [s for s in all_market if not s["is_stop_high"]]
        if not all_market:
            source_kind = "kabutan"
            print("[日本株] 楽天証券取得失敗 → 株探へ切替", file=sys.stderr)
            record_source('kabutan', 'skipped', error='日時未検証の旧PCパーサーはランキングに採用しません')
            stop_high, near_stop = [], []
    print(f"[日本株] S高={len(stop_high)}件 / 上昇率上位={len(near_stop)}件", file=sys.stderr)

    # GitHub Actions などで株探が0件になる場合は、更新済みの日経225データに切替。
    # 対象範囲が異なるため、表示側で「日経225構成銘柄」と明示する。
    if not stop_high and not near_stop:
        fallback = load_nikkei225_fallback()
        if fallback:
            now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()
            output = {
                "updated_at": fallback["source_updated_at"],
                "source_updated_at": fallback["source_updated_at"],
                "last_attempt_at": now,
                "source": "nikkei225_yfinance",
                "source_label": "日経225構成銘柄（Yahoo Finance / yfinance）",
                "scope": "日経225構成銘柄",
                "fetch_status": "fallback",
                "fetch_warning": "全市場ランキングの取得に失敗したため、日経225構成銘柄の値上がり率順を表示しています",
                "session_date": fallback.get('session_date'),
                "source_attempts": FETCH_DIAGNOSTICS,
                "is_fallback": True,
                "stop_high_count": None,
                "near_stop_count": len(fallback["stocks"]),
                "all_stocks": fallback["stocks"],
                "sector_analysis": {},
                "theme_keywords": [],
            }
            safe_save(
                "data/japan_stocks.json",
                output,
                lambda d: (
                    len(d.get("all_stocks", []))
                    if len(d.get("all_stocks", [])) >= RAKUTEN_GLOBAL_TOP
                    else 0
                ),
                label="日本株（日経225代替）",
            )
            print(json.dumps({
                "status": "fallback",
                "scope": output["scope"],
                "all_stocks": len(output["all_stocks"]),
            }))
            return
        from safe_save import mark_failed
        mark_failed('data/japan_stocks.json', '全市場・代替取得元の有効データなし', details={'source_attempts':FETCH_DIAGNOSTICS})
        return

    # 2. 株探経由のときのみ、個別ページから業種を取得
    if source_kind == "kabutan":
        if stop_high:
            stop_high = enrich_sector_kabutan(stop_high)
        if near_stop:
            near_stop = enrich_sector_kabutan(near_stop, max_workers=12)

    # Metadata failures are optional; preserve the ranking and use the cached official master.
    from safe_save import _load_existing
    master_by_code = {x['code']:x for x in (_load_existing(MASTER_CACHE) or {}).get('stocks',[])}
    for stock in stop_high + near_stop:
        metadata=master_by_code.get(stock['code'],{})
        for field in ('name','sector'):
            if metadata.get(field): stock[field]=metadata[field]

    # 3. yfinance でチャート + 会社情報を取得
    sh_target   = stop_high[:CHART_INFO_MAX_STOP_HIGH]
    near_target = near_stop[:CHART_INFO_MAX_NEAR_STOP]

    if sh_target:
        sh_target = enrich_yfinance(sh_target, label="S高銘柄 ")
    if near_target:
        near_target = enrich_yfinance(near_target, max_workers=6, label="上昇率上位 ")

    # near_stop の残り（チャートなし）を補完
    near_rest = near_stop[CHART_INFO_MAX_NEAR_STOP:]
    stop_rest = stop_high[CHART_INFO_MAX_STOP_HIGH:]

    # 4. 全銘柄を change_pct 降順でマージ
    all_stocks = sh_target + stop_rest + near_target + near_rest
    all_stocks.sort(key=change_pct_float, reverse=True)

    from safe_save import _load_existing
    prior = {s['code']:s for s in (_load_existing('data/japan_stocks.json') or {}).get('all_stocks', [])}
    for stock in all_stocks:
        for field in ('description', 'description_ja', 'industry', 'industry_ja', 'website'):
            stock[field] = stock.get(field) or prior.get(stock['code'], {}).get(field)

    # 5. 翻訳（description → description_ja, industry → industry_ja）
    if HAS_TRANSLATE:
        print("[日本株] 事業説明を日本語化中...", file=sys.stderr)
        cache = load_cache()
        all_stocks, cache = enrich_with_translations(all_stocks, cache)
        save_cache(cache)
        print(f"  翻訳キャッシュ保存: {len(cache)}件", file=sys.stderr)

    # 公開ランキングには業種列がないため、補完した業種を表示用にも利用する。
    for stock in all_stocks:
        if not stock.get("sector"):
            stock["sector"] = (
                stock.get("industry_ja")
                or stock.get("industry")
                or "不明"
            )

    # 6. セクター集計・テーマキーワード（S高株ベース）
    sector_analysis = aggregate_by_sector(stop_high)
    theme_keywords = extract_theme_keywords(stop_high, sector_analysis)
    print(f"[日本株] テーマキーワード: {theme_keywords[:8]}", file=sys.stderr)

    jst = datetime.timezone(datetime.timedelta(hours=9))
    is_tse_bulk = source_kind == "tse_bulk"
    is_rakuten = source_kind == "rakuten"
    is_mobile = source_kind == "kabutan_mobile"
    output = {
        "updated_at":      datetime.datetime.now(jst).isoformat(),
        "last_attempt_at": datetime.datetime.now(jst).isoformat(),
        "source":          (
            "jpx_yfinance" if is_tse_bulk
            else "rakuten_securities" if is_rakuten
            else "kabutan_mobile"
        ),
        "source_label":    (
            "JPX公式上場銘柄一覧 × Yahoo Finance日足"
            if is_tse_bulk else
            "楽天証券 公開ランキング（東証P/S/G）"
            if is_rakuten else
            "株探 東証P/S/Gの値上がり率ランキング（15分遅延）"
        ),
        "source_url":      (
            JPX_LIST_PAGE if is_tse_bulk else
            RAKUTEN_RANK_URL.format(market_id=0) if is_rakuten else
            KABUTAN_TSE_URL
        ),
        "scope":           "東証全市場（プライム・スタンダード・グロース）",
        "ranking_definition": (
            "JPX上場内国株式の前日比・値上がり率上位30銘柄"
            if is_tse_bulk else
            f"前日比・値上がり率上位{len(all_stocks)}銘柄"
        ),
        "ranking_count":   len(all_stocks),
        "prices_fetched_at": BULK_METADATA.get('prices_fetched_at') if is_tse_bulk else min((s.get('source_checked_at','') for s in all_stocks), default=None),
        "price_time_precision": "day" if is_tse_bulk else "minute",
        "as_of": min((s.get("source_checked_at", "") for s in all_stocks), default=None) if is_mobile else None,
        "fetch_status":    ("partial" if is_tse_bulk and BULK_METADATA.get('coverage', 0) < 1 else "ok") if is_tse_bulk else "fallback",
        "fetch_warning": ("全市場の取得できた銘柄から算出。取得対象と取得件数を参照してください" if is_tse_bulk and BULK_METADATA.get('coverage', 0) < 1 else "") if is_tse_bulk else ("Yahoo日足の取得に失敗したため、株探の市場日時を検証して上位30件を表示" if is_mobile else "主取得元に失敗したため、楽天証券の東証P/S/G各10件から全市場トップ10を表示"),
        "source_attempts": FETCH_DIAGNOSTICS,
        "coverage": BULK_METADATA if is_tse_bulk else {},
        "session_date": max((s.get('price_date', '') for s in all_stocks), default=''),
        "is_fallback":     False,
        "stop_high_count": len(stop_high),
        "near_stop_count": len(near_stop),
        "all_stocks":      all_stocks,
        "sector_analysis": sector_analysis,
        "theme_keywords":  theme_keywords,
    }

    # 取得失敗（0件）で既存の良いデータを破壊しないようガード
    saved = safe_save(
        "data/japan_stocks.json",
        output,
        lambda d: (
            len(d.get("all_stocks", []))
            if len(d.get("all_stocks", [])) >= RAKUTEN_GLOBAL_TOP
            else 0
        ),
        label="日本株",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "stop_high": len(stop_high),
        "near_stop": len(near_stop),
        "all_stocks": len(all_stocks),
        "theme_keywords": len(theme_keywords),
    }))


if __name__ == "__main__":
    if '--bulk-only' in sys.argv:
        stocks = fetch_tse_all_market()
        print(json.dumps({'stocks':stocks, 'metadata':BULK_METADATA, 'diagnostics':FETCH_DIAGNOSTICS}, ensure_ascii=False, allow_nan=False))
    else:
        main()
