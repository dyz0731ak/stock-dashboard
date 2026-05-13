#!/usr/bin/env python3
"""
急騰理由・ニュース取得スクリプト（APIキー不要・完全無料）

データソース（優先順位順）:
  1. kabutan.jp「開示」「修正」カテゴリ → 適時開示（TDnet相当）
  2. minkabu.jp                          → 急騰理由・ニュース解説
  3. kabutan.jp「材料」カテゴリ          → 株探ニュース

出力: data/news_cache.json
"""

import requests
import json
import datetime
import time
import sys
import os
import re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CACHE_FILE    = "data/news_cache.json"
CACHE_TTL_HRS = 6     # キャッシュ有効時間（時間）
MAX_STOCKS    = 25    # 上位N銘柄まで取得

# 適時開示扱いにする kabutan カテゴリ
TDNET_CATEGORIES = {"開示", "修正", "増配", "配当", "分割", "消却", "公募", "自社株"}
# スキップするカテゴリ（テクニカル・市場全体ニュース）
SKIP_CATEGORIES = {"テク", "話題", "指標"}

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
# kabutan.jp スクレイピング
# ──────────────────────────────────────────────

def fetch_kabutan(code: str) -> list[dict]:
    """
    kabutan.jp の銘柄ニュースページをスクレイピング。
    table.s_news_list の各 tr から日時・カテゴリ・タイトル・URLを取得。
    カテゴリに応じて source を "tdnet" / "kabutan" に振り分け。
    """
    url = f"https://kabutan.jp/stock/news?code={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"    kabutan fetch error ({code}): {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="s_news_list")
    if not table:
        return []

    items: list[dict] = []
    seen: set[str] = set()

    for row in table.find_all("tr"):
        # ── 日時 ──
        time_el = row.find("time")
        date_str = time_el.get_text(strip=True) if time_el else ""

        # ── カテゴリ ──
        ctg_el = row.find("div", class_=lambda c: c and "newslist_ctg" in c)
        category = ctg_el.get_text(strip=True) if ctg_el else ""

        # テクニカル等の不要カテゴリはスキップ
        if category in SKIP_CATEGORIES:
            continue

        # ── タイトル / URL ──
        link = row.find("a", href=True)
        if not link:
            continue
        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        # 重複除去（タイトル先頭20文字）
        key = title[:20]
        if key in seen:
            continue
        seen.add(key)

        href = link["href"]
        if href.startswith("/"):
            full_url = f"https://kabutan.jp{href}"
        elif href.startswith("http"):
            full_url = href
        else:
            full_url = url

        # ソース判定
        if any(cat in category for cat in TDNET_CATEGORIES):
            source, label = "tdnet", "適時開示"
        else:
            source, label = "kabutan", "株探"

        items.append({
            "title":        title,
            "url":          full_url,
            "date":         date_str,
            "category":     category,
            "source":       source,
            "source_label": label,
        })

        if len(items) >= 8:
            break

    print(f"    kabutan: {len(items)}件", file=sys.stderr)
    return items


# ──────────────────────────────────────────────
# minkabu.jp スクレイピング
# ──────────────────────────────────────────────

def fetch_minkabu(code: str) -> list[dict]:
    """
    minkabu.jp の銘柄ニュースページをスクレイピング。
    ul.md_list[data-role=news-list-section] の各 li から取得。
    """
    url = f"https://minkabu.jp/stock/{code}/news"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"    minkabu fetch error ({code}): {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    news_ul = soup.find("ul", attrs={"data-role": "news-list-section"})
    if not news_ul:
        # フォールバック: ul.md_list
        news_ul = soup.find("ul", class_="md_list")
    if not news_ul:
        return []

    items: list[dict] = []
    seen: set[str] = set()

    for li in news_ul.find_all("li", recursive=False):
        # ── タイトル / URL ──
        title_box = li.find("div", class_="title_box")
        if not title_box:
            continue
        link = title_box.find("a", href=True)
        if not link:
            continue

        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        key = title[:20]
        if key in seen:
            continue
        seen.add(key)

        href = link["href"]
        full_url = f"https://minkabu.jp{href}" if href.startswith("/") else href

        # ── 日時（"今日 18:22" / "5月12日 16:00" など）──
        date_str = ""
        flex_divs = li.find_all("div", class_=lambda c: c and "flex" in c and "items-center" in c)
        for d in flex_divs:
            t = d.get_text(strip=True)
            if re.search(r"\d+[:/月日]", t):
                date_str = t
                break

        # ── ニュースソース名（"株探" / "ロイター" など）──
        ch_link = li.find("a", href=lambda h: h and "/news/channel/" in str(h))
        channel = ch_link.get_text(strip=True) if ch_link else ""

        # kabutan 由来は後で kabutan から取得するのでスキップ
        if channel in ("株探",):
            continue

        items.append({
            "title":        title,
            "url":          full_url,
            "date":         date_str,
            "category":     channel,
            "source":       "minkabu",
            "source_label": f"みんかぶ" + (f"/{channel}" if channel else ""),
        })

        if len(items) >= 5:
            break

    print(f"    minkabu: {len(items)}件", file=sys.stderr)
    return items


# ──────────────────────────────────────────────
# 統合・重複除去
# ──────────────────────────────────────────────

def fetch_all_news(code: str) -> list[dict]:
    """
    優先順位: TDnet相当（kabutan開示） → minkabu → kabutan材料
    重複タイトルは除去し最大10件返す。
    """
    print(f"  [{code}] ニュース取得中...", file=sys.stderr)

    kabutan_items = fetch_kabutan(code)
    time.sleep(0.4)
    minkabu_items = fetch_minkabu(code)

    # 優先順位で並べる: TDnet → minkabu → kabutan材料
    tdnet_items   = [i for i in kabutan_items if i["source"] == "tdnet"]
    kabutan_news  = [i for i in kabutan_items if i["source"] == "kabutan"]
    ordered = tdnet_items + minkabu_items + kabutan_news

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
    print("[ニュース] 取得開始...", file=sys.stderr)

    # 対象銘柄を japan_stocks.json から読み込む
    codes_set = set()
    try:
        with open("data/japan_stocks.json", encoding="utf-8") as f:
            jp_data = json.load(f)
        stocks = jp_data.get("all_stocks", [])
        for s in stocks[:MAX_STOCKS]:
            if s.get("code"):
                codes_set.add(s["code"])
    except Exception as e:
        print(f"  japan_stocks.json 読み込みエラー: {e}", file=sys.stderr)

    # volume_stocks.json の JP銘柄も追加
    try:
        with open("data/volume_stocks.json", encoding="utf-8") as f:
            vol_data = json.load(f)
        for s in vol_data.get("jp_stocks", []):
            if s.get("code"):
                codes_set.add(s["code"])
    except Exception as e:
        print(f"  volume_stocks.json 読み込みエラー: {e}", file=sys.stderr)

    codes = list(codes_set)

    print(f"  対象: {len(codes)}銘柄", file=sys.stderr)

    cache = load_cache()
    if "stocks" not in cache:
        cache["stocks"] = {}

    updated = 0
    for code in codes:
        entry = cache["stocks"].get(code)
        if is_fresh(entry):
            print(f"  [{code}] キャッシュ有効 → スキップ", file=sys.stderr)
            continue

        news = fetch_all_news(code)
        cache["stocks"][code] = {
            "fetched_at": datetime.datetime.now(JST).isoformat(),
            "news": news,
        }
        updated += 1
        time.sleep(0.5)

    cache["updated_at"] = datetime.datetime.now(JST).isoformat()
    save_cache(cache)

    total = len(cache.get("stocks", {}))
    print(f"[ニュース] 完了: {updated}銘柄更新 / キャッシュ合計{total}銘柄", file=sys.stderr)
    print(json.dumps({"status": "ok", "updated": updated, "total": len(codes)}))


if __name__ == "__main__":
    main()
