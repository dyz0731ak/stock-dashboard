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
import email.utils
import time
import sys
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote
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
MAX_TOTAL     = 10   # 市場全体を動かす重要トピックに絞る

JST = datetime.timezone(datetime.timedelta(hours=9))

# 株式市場関連のキーワードフィルタ（不要なニュースを除外）
MARKET_KW = [
    "株", "相場", "日経", "東証", "上昇", "下落", "騰", "安",
    "市場", "投資", "証券", "為替", "円", "ドル", "金利", "債券",
    "S&P", "ナスダック", "NYSE", "決算", "業績", "四半期",
    "米国株", "日本株", "株価", "指数", "ETF", "IPO",
]
NEWS_NOISE = ["指数情報・推移", "リアルタイム株価・チャート", "掲示板 - Yahoo"]
MACRO_KW = [
    "日経平均", "TOPIX", "東証", "日本株", "米国株", "NYダウ", "ナスダック",
    "S&P500", "FRB", "FOMC", "日銀", "金利", "国債", "為替", "円安", "円高",
    "ドル円", "半導体", "AI", "中国株", "中国経済", "原油", "関税", "貿易",
    "インフレ", "雇用", "景気", "地政学",
]

TOPIC_RULES = [
    (
        "金融政策",
        ("日銀", "FRB", "FOMC", "金利", "国債", "利上げ", "利下げ"),
        "金利見通しの変化は銀行・保険に追い風／逆風となり、不動産や高PER株の評価にも波及します。",
        ["銀行", "保険", "不動産", "グロース"],
    ),
    (
        "半導体・AI",
        ("半導体", "AI", "エヌビディア", "NVIDIA", "SKハイニックス", "SOX"),
        "海外ハイテク株の流れは、日本の半導体製造装置・電子部品株へ波及しやすい材料です。",
        ["半導体", "電子部品", "精密機器"],
    ),
    (
        "米国市場",
        ("米国株", "NYダウ", "ナスダック", "S&P500", "ウォール街"),
        "米国株のリスク選好は翌営業日の日本株、とくに外需・ハイテク株の寄り付きに影響しやすい材料です。",
        ["半導体", "電機", "自動車", "商社"],
    ),
    (
        "中国・アジア",
        ("中国", "香港", "韓国", "台湾", "アジア株"),
        "中国・アジアの景気や株価は、機械・素材・化粧品など中国売上比率の高い日本企業に波及します。",
        ["機械", "化学", "化粧品", "素材"],
    ),
    (
        "資源・エネルギー",
        ("原油", "天然ガス", "OPEC", "金価格", "資源"),
        "資源価格の変動は商社・石油株の収益と、空運・陸運・製造業のコストに逆方向の影響を与えます。",
        ["商社", "石油", "鉱業", "空運"],
    ),
    (
        "政策・通商",
        ("関税", "貿易", "選挙", "政権", "規制", "経済対策"),
        "政策変更は輸出条件や国内需要を変えるため、関連業種の業績予想と為替反応を確認したい材料です。",
        ["自動車", "機械", "防衛", "内需"],
    ),
    (
        "日本株全体",
        ("日経平均", "TOPIX", "東証", "日本株"),
        "指数全体の動きは市場心理と資金配分の変化を示します。値動きを主導する業種と売買代金を確認したい局面です。",
        ["日経平均", "TOPIX", "主力株"],
    ),
    (
        "為替",
        ("円安", "円高", "ドル円", "為替", "円相場"),
        "円安は輸出企業の採算改善要因、円高は内需・輸入企業のコスト改善要因です。方向転換の有無を確認したい局面です。",
        ["自動車", "機械", "小売", "空運"],
    ),
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


def is_macro_market_news(title):
    """個別銘柄だけの材料を除き、市場全体へ波及するニュースを判定する。"""
    return any(kw.lower() in title.lower() for kw in MACRO_KW)


def enrich_market_item(item):
    """見出しから、日本株への影響を読むための論点を付与する。"""
    title = item.get("title", "")
    source_label = item.get("source_label", "")
    # Google Newsの「見出し - 媒体名」は媒体名を別表示するため末尾だけ除く。
    if source_label and title.endswith(f" - {source_label}"):
        title = title[: -(len(source_label) + 3)].strip()
    item["title"] = title
    for topic, keywords, impact, sectors in TOPIC_RULES:
        if any(word.lower() in title.lower() for word in keywords):
            item["topic"] = topic
            item["impact_summary"] = impact
            item["watch_sectors"] = sectors
            break
    else:
        item["topic"] = "日本株全体"
        item["impact_summary"] = (
            "市場心理や資金の向きが変わる可能性があります。指数だけでなく、"
            "関連業種への波及と翌営業日の売買動向を確認したいニュースです。"
        )
        item["watch_sectors"] = ["日経平均", "TOPIX"]
    item["importance"] = 3 if any(
        word.lower() in title.lower()
        for word in ("日銀", "FRB", "FOMC", "関税", "急落", "暴落", "最高値", "半導体", "円安", "円高")
    ) else 2
    return item


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
# Google ニュース RSS（既存3ソースが取得できない場合の公開RSS代替）
# ──────────────────────────────────────────────

def fetch_google_news_rss(query, source_key, label, limit=MAX_PER_SRC):
    """Google ニュースの公開RSSから指定テーマの市場ニュースを取得。"""
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote(query)}"
        "&hl=ja&gl=JP&ceid=JP:ja"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"  google news rss error: {e}", file=sys.stderr)
        return []

    now = datetime.datetime.now(datetime.timezone.utc)
    items = []
    seen = set()
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub = (node.findtext("pubDate") or "").strip()
        source_node = node.find("source")
        publisher = (source_node.text or "").strip() if source_node is not None else ""
        if (not title or not link or not is_market_related(title)
                or any(noise in title for noise in NEWS_NOISE)):
            continue
        try:
            published = email.utils.parsedate_to_datetime(pub)
            if published.tzinfo is None:
                published = published.replace(tzinfo=datetime.timezone.utc)
            # 古い記事が混ざらないよう直近48時間に限定
            if (now - published.astimezone(datetime.timezone.utc)).total_seconds() > 48 * 3600:
                continue
            date_str = published.astimezone(JST).strftime("%m/%d %H:%M")
        except Exception:
            date_str = ""
        key = title[:25]
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title,
            "url": link,
            "date": date_str,
            "source": source_key,
            "source_label": publisher or label,
        })
        if len(items) >= limit:
            break

    print(f"  {label}: {len(items)}件", file=sys.stderr)
    return items


# ──────────────────────────────────────────────
# 統合・重複除去
# ──────────────────────────────────────────────

def fetch_all_market_news():
    """全ソースからニュースを取得して統合・重複除去して返す"""

    preferred_specs = [
        (
            "(日本株 OR 日経平均 OR 円相場 OR 日銀 OR 米国株 OR ナスダック) when:2d site:nikkei.com",
            "nikkei", "日本経済新聞", 3,
        ),
        (
            "(日本株 OR 日経平均 OR 円相場 OR 日銀 OR 米国株) when:2d site:mainichi.jp",
            "mainichi", "毎日新聞", 2,
        ),
        (
            "(Japan stocks OR Nikkei OR yen OR BOJ OR Federal Reserve OR Nasdaq) when:2d site:wsj.com",
            "wsj", "The Wall Street Journal", 2,
        ),
        (
            "(日本株 OR 日経平均 OR 円相場 OR 日銀 OR 米国株 OR 半導体) when:2d site:reuters.com",
            "reuters", "ロイター", 3,
        ),
    ]
    preferred = []
    source_counts = {}
    for query, key, label, limit in preferred_specs:
        fetched = fetch_google_news_rss(query, key, label, limit=limit)
        preferred.extend(fetched)
        source_counts[key] = len(fetched)
        time.sleep(0.35)

    broad = fetch_google_news_rss(
        "(日本株 OR 日経平均 OR 東証 OR 円相場 OR 日銀 OR 米国株 OR ナスダック OR 半導体 OR 原油) when:2d",
        "market_press",
        "主要メディア",
        limit=12,
    )
    time.sleep(0.35)
    kabutan_items = [
        item for item in fetch_kabutan_market()
        if is_macro_market_news(item.get("title", ""))
    ]

    # 媒体の偏りを抑えながら、個別銘柄ではなく市場全体に効く見出しを採用。
    seen = set()
    per_publisher = {}
    result = []
    for item in preferred + broad + kabutan_items:
        if not is_macro_market_news(item.get("title", "")):
            continue
        publisher = item.get("source_label") or item.get("source") or "その他"
        if per_publisher.get(publisher, 0) >= 3:
            continue
        key = re.sub(r"\s+", "", item["title"]).lower()[:32]
        if key in seen:
            continue
        seen.add(key)
        per_publisher[publisher] = per_publisher.get(publisher, 0) + 1
        result.append(enrich_market_item(item))
        if len(result) >= MAX_TOTAL:
            break

    print(f"  合計: {len(result)}件（重複除去後）", file=sys.stderr)
    source_counts.update({
        "broad_market_press": len(broad),
        "kabutan_macro": len(kabutan_items),
    })
    return result[:MAX_TOTAL], source_counts


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

def main():
    print("[市場ニュース] 取得開始...", file=sys.stderr)

    cache = load_cache()
    if os.environ.get("FORCE_REFRESH") != "1" and is_fresh(cache):
        print("[市場ニュース] キャッシュ有効 → スキップ", file=sys.stderr)
        print(json.dumps({"status": "cached", "count": len(cache.get("items", []))}))
        return

    items, source_counts = fetch_all_market_news()
    now = datetime.datetime.now(JST).isoformat()

    result = {
        "items":      items,
        "updated_at": now,
        "last_attempt_at": now,
        "fetch_status": "ok" if items else "stale",
        "source_counts": source_counts,
    }
    # 取得失敗（0件）で既存の良いデータを破壊しないようガード
    saved = safe_save(
        CACHE_FILE,
        result,
        lambda d: len(d.get("items", [])),
        label="市場ニュース",
        failure_reason="市場ニュースの全取得元で新着記事を取得できませんでした",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "count": len(items),
    }))


if __name__ == "__main__":
    main()
