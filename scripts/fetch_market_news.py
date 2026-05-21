#!/usr/bin/env python3
"""
本日の市場ニュース取得スクリプト（APIキー不要・完全無料）

データソース（優先順位順）:
  1. kabutan.jp（株探）マーケットニュース
  2. minkabu.jp マーケットニュース
  3. Yahoo Finance Japan マーケットニュース

出力: data/market_news.json
"""

import requests
import json
import datetime
import time
import sys
import os
import re
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CACHE_FILE    = "data/market_news.json"
CACHE_TTL_MIN = 20   # キャッシュ有効時間（分）
MAX_PER_SRC   = 8    # ソースあたり最大件数
MAX_TOTAL     = 15   # 合計最大件数

JST = datetime.timezone(datetime.timedelta(hours=9))

# 株式市場関連のキーワードフィルタ（不要なニュースを除外）
MARKET_KW = [
    "株", "相場", "日経", "東証", "上昇", "下落", "騰", "安",
    "市場", "投資", "証券", "為替", "円", "ドル", "金利", "債券",
    "S&P", "ナスダック", "NYSE", "決算", "業績", "四半期",
    "米国株", "日本株", "株価", "指数", "ETF", "IPO",
]


# ──────────────────────────────────────────────
# キャッシュ管理
# ──────────────────────────────────────────────

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(data):
    os.makedirs("data", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_fresh(cache):
    if not cache or "updated_at" not in cache:
        return False
    # 0件キャッシュは「新しい」とみなさない（取得失敗の固定化を防ぐ）
    if not cache.get("items"):
        return False
    try:
        updated = datetime.datetime.fromisoformat(cache["updated_at"])
        now = datetime.datetime.now(JST)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=JST)
        return (now - updated).total_seconds() < CACHE_TTL_MIN * 60
    except Exception:
        return False


def is_market_related(title):
    """株式市場関連ニュースかどうかを判定"""
    return any(kw in title for kw in MARKET_KW)


# ──────────────────────────────────────────────
# kabutan.jp マーケットニュース
# ──────────────────────────────────────────────

def fetch_kabutan_market():
    """
    株探(kabutan.jp) のマーケットニュースページをスクレイピング。
    table.s_news_list の各 tr から日時・タイトル・URL を取得。
    """
    urls = [
        "https://kabutan.jp/news/marketnews/",
        "https://kabutan.jp/news/?b=n202505",  # フォールバック
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
        except Exception as e:
            print(f"  kabutan fetch error: {e}", file=sys.stderr)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # パターン1: table.s_news_list（株探共通テーブル）
        table = soup.find("table", class_="s_news_list")
        if table:
            items = []
            seen = set()
            for row in table.find_all("tr"):
                time_el = row.find("time")
                date_str = time_el.get_text(strip=True) if time_el else ""

                # スキップカテゴリ
                ctg_el = row.find("div", class_=lambda c: c and "newslist_ctg" in c)
                category = ctg_el.get_text(strip=True) if ctg_el else ""
                if category in {"テク"}:
                    continue

                link = row.find("a", href=True)
                if not link:
                    continue
                title = link.get_text(strip=True)
                if not title or len(title) < 8:
                    continue
                key = title[:20]
                if key in seen:
                    continue
                seen.add(key)

                href = link["href"]
                full_url = f"https://kabutan.jp{href}" if href.startswith("/") else href

                items.append({
                    "title":        title,
                    "url":          full_url,
                    "date":         date_str,
                    "source":       "kabutan",
                    "source_label": "株探",
                })
                if len(items) >= MAX_PER_SRC:
                    break

            if items:
                print(f"  kabutan: {len(items)}件", file=sys.stderr)
                return items

        # パターン2: 汎用リンク探索
        items = []
        seen = set()
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            if not is_market_related(title):
                continue
            key = title[:20]
            if key in seen:
                continue
            seen.add(key)

            href = a["href"]
            full_url = f"https://kabutan.jp{href}" if href.startswith("/") else href
            if "kabutan.jp" not in full_url and not href.startswith("/"):
                continue

            # 日時は取れないので空
            items.append({
                "title":        title,
                "url":          full_url,
                "date":         "",
                "source":       "kabutan",
                "source_label": "株探",
            })
            if len(items) >= MAX_PER_SRC:
                break

        if items:
            print(f"  kabutan (fallback): {len(items)}件", file=sys.stderr)
            return items

    print("  kabutan: 0件", file=sys.stderr)
    return []


# ──────────────────────────────────────────────
# minkabu.jp マーケットニュース
# ──────────────────────────────────────────────

def fetch_minkabu_market():
    """
    minkabu.jp の市場ニュースページをスクレイピング。
    """
    urls = [
        "https://minkabu.jp/news/market",
        "https://minkabu.jp/news/",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
        except Exception as e:
            print(f"  minkabu fetch error: {e}", file=sys.stderr)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # パターン1: ul[data-role=news-list-section]
        news_ul = soup.find("ul", attrs={"data-role": "news-list-section"})
        if not news_ul:
            news_ul = soup.find("ul", class_="md_list")

        if news_ul:
            items = []
            seen = set()
            for li in news_ul.find_all("li", recursive=False):
                title_box = li.find("div", class_="title_box")
                if not title_box:
                    continue
                link = title_box.find("a", href=True)
                if not link:
                    continue

                title = link.get_text(strip=True)
                if not title or len(title) < 8:
                    continue
                key = title[:20]
                if key in seen:
                    continue
                seen.add(key)

                href = link["href"]
                full_url = f"https://minkabu.jp{href}" if href.startswith("/") else href

                # 日時
                date_str = ""
                for d in li.find_all("div", class_=lambda c: c and "flex" in c and "items-center" in c):
                    t = d.get_text(strip=True)
                    if re.search(r"\d+[:/月日]", t):
                        date_str = t
                        break

                # ソース名
                ch_link = li.find("a", href=lambda h: h and "/news/channel/" in str(h))
                channel = ch_link.get_text(strip=True) if ch_link else ""

                items.append({
                    "title":        title,
                    "url":          full_url,
                    "date":         date_str,
                    "source":       "minkabu",
                    "source_label": "みんかぶ" + (f"/{channel}" if channel else ""),
                })
                if len(items) >= MAX_PER_SRC:
                    break

            if items:
                print(f"  minkabu: {len(items)}件", file=sys.stderr)
                return items

    print("  minkabu: 0件", file=sys.stderr)
    return []


# ──────────────────────────────────────────────
# Yahoo Finance Japan マーケットニュース
# ──────────────────────────────────────────────

def fetch_yahoo_finance_jp():
    """
    Yahoo Finance Japan のマーケットニュースをスクレイピング。
    """
    try:
        url = "https://finance.yahoo.co.jp/news/category/market"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  yahoo finance jp: {resp.status_code}", file=sys.stderr)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        seen = set()

        # Yahoo Finance Japan のニュースリスト（複数パターン試行）
        # パターン1: ul > li 形式
        for li in soup.find_all("li"):
            link = li.find("a", href=True)
            if not link:
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            if not is_market_related(title):
                continue
            key = title[:20]
            if key in seen:
                continue
            seen.add(key)

            href = link["href"]
            full_url = href if href.startswith("http") else f"https://finance.yahoo.co.jp{href}"

            # 日時
            time_el = li.find("time")
            date_str = time_el.get_text(strip=True) if time_el else ""

            items.append({
                "title":        title,
                "url":          full_url,
                "date":         date_str,
                "source":       "yahoo_jp",
                "source_label": "Yahoo Finance",
            })
            if len(items) >= MAX_PER_SRC:
                break

        if items:
            print(f"  yahoo finance jp: {len(items)}件", file=sys.stderr)
        else:
            print("  yahoo finance jp: 0件", file=sys.stderr)
        return items

    except Exception as e:
        print(f"  yahoo finance jp error: {e}", file=sys.stderr)
        return []


# ──────────────────────────────────────────────
# 統合・重複除去
# ──────────────────────────────────────────────

def fetch_all_market_news():
    """全ソースからニュースを取得して統合・重複除去して返す"""

    kabutan_items  = fetch_kabutan_market()
    time.sleep(0.5)
    minkabu_items  = fetch_minkabu_market()
    time.sleep(0.5)
    yahoo_items    = fetch_yahoo_finance_jp()

    # 統合（優先順位順）
    all_items = kabutan_items + minkabu_items + yahoo_items

    # タイトルで重複除去
    seen = set()
    result = []
    for item in all_items:
        key = item["title"][:25]
        if key not in seen:
            seen.add(key)
            result.append(item)

    print(f"  合計: {len(result)}件（重複除去後）", file=sys.stderr)
    return result[:MAX_TOTAL]


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

def main():
    print("[市場ニュース] 取得開始...", file=sys.stderr)

    cache = load_cache()
    if is_fresh(cache):
        print("[市場ニュース] キャッシュ有効 → スキップ", file=sys.stderr)
        print(json.dumps({"status": "cached", "count": len(cache.get("items", []))}))
        return

    items = fetch_all_market_news()

    result = {
        "items":      items,
        "updated_at": datetime.datetime.now(JST).isoformat(),
    }
    # 取得失敗（0件）で既存の良いデータを破壊しないようガード
    saved = safe_save(
        CACHE_FILE,
        result,
        lambda d: len(d.get("items", [])),
        label="市場ニュース",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "count": len(items),
    }))


if __name__ == "__main__":
    main()
