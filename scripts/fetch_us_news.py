#!/usr/bin/env python3
"""
米国株ニュース取得スクリプト（APIキー不要・完全無料）

データソース（優先順位順）:
  1. investing.com 日本語版: https://jp.investing.com/equities/{slug}-news
  2. yfinance .news プロパティ（Yahoo Finance APIバックエンド）

出力: data/us_news_cache.json
"""

import requests
import json
import datetime
import time
import sys
import os
import re
from typing import Optional
import yfinance as yf
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CACHE_FILE    = "data/us_news_cache.json"
CACHE_TTL_HRS = 6    # キャッシュ有効時間（時間）
MAX_STOCKS    = 40   # 最大取得銘柄数

JST = datetime.timezone(datetime.timedelta(hours=9))


# ──────────────────────────────────────────────
# キャッシュ管理
# ──────────────────────────────────────────────

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def is_fresh(entry, ttl_hours: int = CACHE_TTL_HRS) -> bool:
    if not entry or "fetched_at" not in entry:
        return False
    try:
        fetched = datetime.datetime.fromisoformat(entry["fetched_at"])
        now = datetime.datetime.now(JST)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=JST)
        return (now - fetched).total_seconds() < ttl_hours * 3600
    except Exception:
        return False


# ──────────────────────────────────────────────
# investing.com Japan スラッグ生成
# ──────────────────────────────────────────────

def name_to_investing_slug(name: str) -> str:
    name = re.sub(r'\b(Inc\.?|Corp\.?|Co\.?|Ltd\.?|LLC|L\.P\.?|PLC|N\.V\.|SE|AG)\b', '', name, flags=re.IGNORECASE)
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    name = re.sub(r'\s+', '-', name.strip())
    name = re.sub(r'-+', '-', name).strip('-')
    return name


# ──────────────────────────────────────────────
# investing.com Japan スクレイピング
# ──────────────────────────────────────────────

def fetch_investing_jp(symbol: str, name: str) -> list[dict]:
    """
    investing.com 日本語版の銘柄ニュースページをスクレイピング。
    失敗時は静かにスキップして空リストを返す。
    """
    slug = name_to_investing_slug(name)
    if not slug:
        return []

    url = f"https://jp.investing.com/equities/{slug}-news"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        items: list[dict] = []
        seen: set[str] = set()

        # investing.com のニュース記事要素を探す
        # 複数のセレクタパターンを試みる
        article_links = []

        # パターン1: data-test="article-title-link" 属性
        for a in soup.find_all("a", attrs={"data-test": "article-title-link"}):
            article_links.append(a)

        # パターン2: class に "article" を含む div 内の a タグ
        if not article_links:
            for article in soup.find_all(["article", "div"], class_=lambda c: c and "article" in c.lower()):
                for a in article.find_all("a", href=True):
                    title_text = a.get_text(strip=True)
                    if title_text and len(title_text) > 10:
                        article_links.append(a)
                        break

        # パターン3: /news/ を含む href の a タグ
        if not article_links:
            for a in soup.find_all("a", href=lambda h: h and "/news/" in str(h)):
                title_text = a.get_text(strip=True)
                if title_text and len(title_text) > 10:
                    article_links.append(a)

        for a in article_links:
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            key = title[:25]
            if key in seen:
                continue
            seen.add(key)

            href = a.get("href", "")
            if href.startswith("/"):
                full_url = f"https://jp.investing.com{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                continue

            # 日時を探す（親要素や隣接要素から）
            date_str = ""
            parent = a.parent
            for _ in range(3):
                if parent is None:
                    break
                time_el = parent.find("time")
                if time_el:
                    date_str = time_el.get_text(strip=True)
                    break
                # span などに日時テキストがある場合
                for span in parent.find_all(["span", "div"]):
                    t = span.get_text(strip=True)
                    if re.search(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[月/]\d{1,2}', t):
                        date_str = t
                        break
                if date_str:
                    break
                parent = parent.parent

            items.append({
                "title":        title,
                "url":          full_url,
                "date":         date_str,
                "source":       "investing_jp",
                "source_label": "investing.com",
            })

            if len(items) >= 5:
                break

        if items:
            print(f"    investing.com: {len(items)}件", file=sys.stderr)
        return items

    except Exception:
        return []


# ──────────────────────────────────────────────
# yfinance ニュース取得
# ──────────────────────────────────────────────

def parse_yfinance_news_item(item: dict) -> Optional[dict]:
    """
    yfinance の news エントリを正規化する。
    新形式: {"id": "...", "content": {"title": ..., "provider": ..., "canonicalUrl": ..., "pubDate": ...}}
    旧形式: {"title": ..., "publisher": ..., "link": ..., "providerPublishTime": ...}
    """
    try:
        # 新形式
        if "content" in item and isinstance(item["content"], dict):
            content = item["content"]
            title = content.get("title", "")
            if not title:
                return None

            # URL: canonicalUrl または clickThroughUrl
            url = ""
            for url_key in ("canonicalUrl", "clickThroughUrl"):
                url_obj = content.get(url_key)
                if url_obj and isinstance(url_obj, dict):
                    url = url_obj.get("url", "")
                    if url:
                        break

            if not url:
                return None

            # 発行者名
            provider_obj = content.get("provider")
            if provider_obj and isinstance(provider_obj, dict):
                publisher = provider_obj.get("displayName", "Yahoo Finance")
            else:
                publisher = "Yahoo Finance"

            # 日時
            pub_date_str = content.get("pubDate", "")
            date_str = ""
            if pub_date_str:
                try:
                    dt = datetime.datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    dt_jst = dt.astimezone(JST)
                    date_str = dt_jst.strftime("%m/%d %H:%M")
                except Exception:
                    date_str = pub_date_str[:16] if len(pub_date_str) >= 16 else pub_date_str

            return {
                "title":        title,
                "url":          url,
                "date":         date_str,
                "source":       "yahoo_finance",
                "source_label": f"Yahoo Finance / {publisher}",
            }

        # 旧形式
        title = item.get("title", "")
        url = item.get("link", "")
        if not title or not url:
            return None

        publisher = item.get("publisher", "Yahoo Finance")
        pub_time = item.get("providerPublishTime")
        date_str = ""
        if pub_time:
            try:
                dt = datetime.datetime.fromtimestamp(pub_time, tz=JST)
                date_str = dt.strftime("%m/%d %H:%M")
            except Exception:
                pass

        return {
            "title":        title,
            "url":          url,
            "date":         date_str,
            "source":       "yahoo_finance",
            "source_label": f"Yahoo Finance / {publisher}",
        }

    except Exception:
        return None


def fetch_yfinance_news(symbol: str) -> list[dict]:
    """
    yfinance の .news プロパティからニュースを取得する。
    """
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news
        if not raw_news:
            return []

        items: list[dict] = []
        seen: set[str] = set()

        for item in raw_news:
            if not isinstance(item, dict):
                continue
            parsed = parse_yfinance_news_item(item)
            if parsed is None:
                continue
            key = parsed["title"][:25]
            if key in seen:
                continue
            seen.add(key)
            items.append(parsed)
            if len(items) >= 8:
                break

        print(f"    yfinance: {len(items)}件", file=sys.stderr)
        return items

    except Exception as e:
        print(f"    yfinance fetch error ({symbol}): {e}", file=sys.stderr)
        return []


# ──────────────────────────────────────────────
# 統合・重複除去
# ──────────────────────────────────────────────

def fetch_all_news(symbol: str, name: str) -> list[dict]:
    """
    優先順位: investing.com Japan → yfinance
    重複タイトルは除去し最大10件返す。
    """
    print(f"  [{symbol}] ニュース取得中...", file=sys.stderr)

    investing_items = fetch_investing_jp(symbol, name)
    time.sleep(0.3)
    yfinance_items = fetch_yfinance_news(symbol)

    ordered = investing_items + yfinance_items

    # 重複除去
    seen: set[str] = set()
    result: list[dict] = []
    for item in ordered:
        key = item["title"][:25]
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result[:10]


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

def main():
    print("[米国株ニュース] 取得開始...", file=sys.stderr)

    # 対象銘柄を収集
    stocks_map: dict[str, str] = {}  # symbol -> name

    # us_stocks.json の gainers リスト
    try:
        with open("data/us_stocks.json", encoding="utf-8") as f:
            us_data = json.load(f)
        for s in us_data.get("gainers", []):
            sym = s.get("symbol", "").strip()
            name = s.get("name", sym)
            if sym:
                stocks_map[sym] = name
    except Exception as e:
        print(f"  us_stocks.json 読み込みエラー: {e}", file=sys.stderr)

    # volume_stocks.json の us_stocks リスト
    try:
        with open("data/volume_stocks.json", encoding="utf-8") as f:
            vol_data = json.load(f)
        for s in vol_data.get("us_stocks", []):
            sym = s.get("symbol", "").strip()
            name = s.get("name", sym)
            if sym:
                stocks_map[sym] = name
    except Exception as e:
        print(f"  volume_stocks.json 読み込みエラー: {e}", file=sys.stderr)

    # MAX_STOCKS まで絞る
    symbols = list(stocks_map.keys())[:MAX_STOCKS]
    print(f"  対象: {len(symbols)}銘柄", file=sys.stderr)

    cache = load_cache()
    if "stocks" not in cache:
        cache["stocks"] = {}

    updated = 0
    for symbol in symbols:
        entry = cache["stocks"].get(symbol)
        if is_fresh(entry):
            print(f"  [{symbol}] キャッシュ有効 → スキップ", file=sys.stderr)
            continue

        name = stocks_map[symbol]
        news = fetch_all_news(symbol, name)
        cache["stocks"][symbol] = {
            "fetched_at": datetime.datetime.now(JST).isoformat(),
            "news": news,
        }
        updated += 1
        time.sleep(0.5)

    cache["updated_at"] = datetime.datetime.now(JST).isoformat()
    save_cache(cache)

    total = len(cache.get("stocks", {}))
    print(f"[米国株ニュース] 完了: {updated}銘柄更新 / キャッシュ合計{total}銘柄", file=sys.stderr)
    print(json.dumps({"status": "ok", "updated": updated, "total": len(symbols)}))


if __name__ == "__main__":
    main()
