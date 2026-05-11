#!/usr/bin/env python3
"""
kabutan.jp ストップ高ページ (mode=2_1) + yfinance で
チャート・会社情報・テーマキーワードを一括取得

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
  chart: { dates, closes, volumes } (6ヶ月日足)
"""

import requests
from bs4 import BeautifulSoup
import json
import datetime
import re
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
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

# チャート・会社情報を取得する対象（件数制限で Actions 時間を節約）
CHART_INFO_MAX_STOP_HIGH = 50   # S高全件
CHART_INFO_MAX_NEAR_STOP = 20   # 上昇率上位上位 N 件

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
        hist = t.history(period="6mo", interval="1d", auto_adjust=True)
        chart = None
        if not hist.empty:
            chart = {
                "dates":   [d.strftime("%Y-%m-%d") for d in hist.index],
                "closes":  [round(float(v), 1) if v == v else None
                            for v in hist["Close"]],
                "volumes": [int(v) if v == v else None
                            for v in hist["Volume"]],
            }

        # ── 会社情報 ──
        info = t.info or {}
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
            code, chart, company = fut.result()
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


def main():
    print("[日本株] 取得開始...", file=sys.stderr)

    # 1. S高 + 上昇率上位を取得
    stop_high, near_stop = fetch_stop_high_pages()
    print(f"[日本株] S高={len(stop_high)}件 / 上昇率上位={len(near_stop)}件", file=sys.stderr)

    # 2. 全銘柄の業種を kabutan から取得（S高 + 上昇率上位）
    if stop_high:
        stop_high = enrich_sector_kabutan(stop_high)
    if near_stop:
        near_stop = enrich_sector_kabutan(near_stop, max_workers=12)

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

    # 5. セクター集計（S高株ベース）
    sector_analysis = aggregate_by_sector(stop_high)

    # 6. テーマキーワード抽出
    theme_keywords = extract_theme_keywords(stop_high, sector_analysis)
    print(f"[日本株] テーマキーワード: {theme_keywords[:8]}", file=sys.stderr)

    # 7. 翻訳（description → description_ja, industry → industry_ja）
    if HAS_TRANSLATE:
        print("[日本株] 事業説明を日本語化中...", file=sys.stderr)
        cache = load_cache()
        all_stocks, cache = enrich_with_translations(all_stocks, cache)
        save_cache(cache)
        print(f"  翻訳キャッシュ保存: {len(cache)}件", file=sys.stderr)

    jst = datetime.timezone(datetime.timedelta(hours=9))
    output = {
        "updated_at":      datetime.datetime.now(jst).isoformat(),
        "stop_high_count": len(stop_high),
        "near_stop_count": len(near_stop),
        "all_stocks":      all_stocks,
        "sector_analysis": sector_analysis,
        "theme_keywords":  theme_keywords,
    }

    out_path = "data/japan_stocks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[日本株] 保存: {out_path}", file=sys.stderr)
    print(json.dumps({
        "status": "ok",
        "stop_high": len(stop_high),
        "near_stop": len(near_stop),
        "all_stocks": len(all_stocks),
        "theme_keywords": len(theme_keywords),
    }))


if __name__ == "__main__":
    main()
