#!/usr/bin/env python3
"""
kabutan.jp ストップ高ページ (mode=2_1) から銘柄をスクレイピング

確認済みページ構造（2026-05-11）:
  URL: https://kabutan.jp/warning/?mode=2_1&market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page=N
  テーブル: <table class="stock_table st_market">
  列: [0]コード [1]銘柄名 [2]市場 [3]概要icon [4]チャートicon
      [5]株価 [6]S高フラグ(<span class="up">S</span>) [7]前日比 [8]変化率% [9]出来高
  業種: /stock/?code=XXXX の <th>業種</th> 次の <td>

最適化方針:
  - 銘柄は変化率降順 → S高株は必ず上位ページに出現
  - STOP_AFTER_NO_S_PAGES 連続ページでS高株が出なくなったら打ち切り
  - 業種取得はS高株のみ（並列リクエスト）
  - 上昇率上位表示用に上位 TOP_NEAR_STOP 件も保持
"""

import requests
from bs4 import BeautifulSoup
import json
import datetime
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://kabutan.jp"
LIST_URL = (
    BASE_URL
    + "/warning/?mode=2_1&market=0&capitalization=-1"
    + "&dispmode=normal&stc=&stm=0&page={page}"
)
DETAIL_URL = BASE_URL + "/stock/?code={code}"

# ページ走査の上限・打ち切り設定
MAX_PAGES          = 20   # 最大何ページまで見るか（S高株は通常すべて上位5ページ内）
STOP_AFTER_NO_S    = 3    # S高株が連続でこの回数出なかったら打ち切り
TOP_NEAR_STOP      = 50   # S高以外の上昇率上位を何件保持するか

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get_total_pages(soup):
    """ページネーションから最終ページ番号を取得"""
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
    stock_table の各行をパースして銘柄データのリストを返す

    確認済み列マッピング:
      cols[0] = コード  (td.tac > a)
      cols[1] = 銘柄名  (th.tal)
      cols[2] = 市場    (td.tac)
      cols[3] = 概要icon
      cols[4] = チャートicon
      cols[5] = 現在値（株価）
      cols[6] = S高フラグ  span.up が "S" ならストップ高
      cols[7] = 前日比（金額）
      cols[8] = 変化率%
      cols[9] = 出来高
    """
    table = soup.find("table", class_="stock_table")
    if not table:
        return []

    stocks = []
    for row in table.find_all("tr")[1:]:   # ヘッダー行スキップ
        cols = row.find_all(["td", "th"])
        if len(cols) < 9:
            continue
        try:
            # ── コード ──
            code_a = cols[0].find("a")
            code   = code_a.get_text(strip=True) if code_a else cols[0].get_text(strip=True)
            if not re.match(r"^\d{4}$", code):
                continue

            # ── 銘柄名 ──
            name = cols[1].get_text(strip=True)

            # ── 市場 ──
            market = cols[2].get_text(strip=True)

            # ── 現在値（株価） ──
            price_raw = cols[5].get_text(strip=True).replace(",", "")
            price     = float(price_raw) if price_raw and price_raw not in ("-", "") else None

            # ── S高フラグ ──
            flag_span  = cols[6].find("span", class_="up")
            is_stop_high = bool(flag_span and flag_span.get_text(strip=True) == "S")

            # ── 前日比（金額） ──
            chg_span       = cols[7].find("span") or cols[7]
            change_amount  = chg_span.get_text(strip=True).replace(",", "")

            # ── 変化率% ──
            change_pct_raw = cols[8].get_text(strip=True)
            change_pct     = change_pct_raw.replace("%", "").strip()

            # ── 出来高 ──
            vol_raw = cols[9].get_text(strip=True).replace(",", "") if len(cols) > 9 else ""
            volume  = int(vol_raw) if vol_raw.isdigit() else None

            stocks.append({
                "code":           code,
                "name":           name,
                "market":         market,
                "price":          price,
                "stop_high_price": price,   # S高時は現在値＝ストップ高値
                "is_stop_high":   is_stop_high,
                "change_amount":  change_amount,
                "change_pct":     change_pct,
                "volume":         volume,
                "sector":         None,     # 後で補完（S高株のみ）
            })
        except Exception as e:
            print(f"    行パースエラー: {e}", file=sys.stderr)
            continue

    return stocks


def fetch_sector(code):
    """個別銘柄ページ /stock/?code=XXXX から業種を取得"""
    try:
        resp = SESSION.get(DETAIL_URL.format(code=code), timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for th in soup.find_all("th"):
            if th.get_text(strip=True) == "業種":
                td = th.find_next_sibling("td")
                if td:
                    return code, td.get_text(strip=True)
        return code, "不明"
    except Exception as e:
        print(f"    業種取得失敗 {code}: {e}", file=sys.stderr)
        return code, "不明"


def fetch_stop_high_stocks():
    """
    変化率上位ページを走査してS高株を収集する。
    S高株が連続 STOP_AFTER_NO_S ページ出なくなったら打ち切り。
    """
    all_stop_high = []
    all_near_stop = []   # S高以外の上昇率上位銘柄（上位 TOP_NEAR_STOP 件分）
    no_s_streak   = 0
    total_pages   = None

    print(f"  ストップ高ページ走査（最大{MAX_PAGES}ページ）...", file=sys.stderr)

    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            time.sleep(0.4)   # サーバー負荷軽減

        try:
            resp = SESSION.get(LIST_URL.format(page=page), timeout=20)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  page {page} 取得失敗: {e}", file=sys.stderr)
            continue

        if total_pages is None:
            total_pages = get_total_pages(soup)
            print(f"  総ページ数: {total_pages}（上位{MAX_PAGES}ページを走査）", file=sys.stderr)

        rows = parse_table_rows(soup)
        s_in_page = [r for r in rows if r["is_stop_high"]]
        n_in_page = [r for r in rows if not r["is_stop_high"]]

        all_stop_high.extend(s_in_page)
        # 上昇率上位は上限まで収集
        if len(all_near_stop) < TOP_NEAR_STOP:
            all_near_stop.extend(n_in_page[: TOP_NEAR_STOP - len(all_near_stop)])

        print(
            f"  page {page}/{min(MAX_PAGES, total_pages or MAX_PAGES)}: "
            f"全{len(rows)}件 うちS高={len(s_in_page)}件"
            f"（累計S高={len(all_stop_high)}件）",
            file=sys.stderr,
        )

        # S高株がなくなったらカウント
        if s_in_page:
            no_s_streak = 0
        else:
            no_s_streak += 1
            if no_s_streak >= STOP_AFTER_NO_S:
                print(
                    f"  → {STOP_AFTER_NO_S}ページ連続でS高なし → 走査打ち切り",
                    file=sys.stderr,
                )
                break

    return all_stop_high, all_near_stop


def enrich_sectors(stocks, max_workers=10):
    """並列リクエストで業種情報を補完（S高株のみ対象）"""
    if not stocks:
        return stocks

    print(f"  業種情報取得中（{len(stocks)}件, {max_workers}並列）...", file=sys.stderr)
    sector_map = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_sector, s["code"]): s["code"] for s in stocks}
        for future in as_completed(futures):
            code, sector = future.result()
            sector_map[code] = sector

    for s in stocks:
        s["sector"] = sector_map.get(s["code"], "不明")

    return stocks


def aggregate_by_sector(stocks):
    """業種別集計（件数降順）"""
    sector_count = {}
    for s in stocks:
        sector = s.get("sector") or "不明"
        if sector not in sector_count:
            sector_count[sector] = {"count": 0, "codes": []}
        sector_count[sector]["count"] += 1
        sector_count[sector]["codes"].append(s["code"])

    return dict(
        sorted(sector_count.items(), key=lambda x: x[1]["count"], reverse=True)
    )


def main():
    print("[日本株] 取得開始...", file=sys.stderr)

    # S高株 + 上昇率上位取得
    stop_high, near_stop = fetch_stop_high_stocks()

    print(f"[日本株] ストップ高: {len(stop_high)}件 / 上昇率上位: {len(near_stop)}件", file=sys.stderr)

    # S高株のみ業種を補完
    if stop_high:
        stop_high = enrich_sectors(stop_high)

    # セクター別集計
    sector_analysis = aggregate_by_sector(stop_high)

    jst = datetime.timezone(datetime.timedelta(hours=9))
    output = {
        "updated_at":      datetime.datetime.now(jst).isoformat(),
        "stop_high_count": len(stop_high),
        "near_stop_count": len(near_stop),
        "stop_high":       stop_high,
        "near_stop":       near_stop,
        "sector_analysis": sector_analysis,
    }

    out_path = "data/japan_stocks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[日本株] 保存: {out_path}", file=sys.stderr)
    print(json.dumps({"status": "ok", "stop_high": len(stop_high), "near_stop": len(near_stop)}))


if __name__ == "__main__":
    main()
