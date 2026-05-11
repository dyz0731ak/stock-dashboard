#!/usr/bin/env python3
"""
kabutan.jp からストップ高銘柄をスクレイピングして JSON に保存するスクリプト
"""

import requests
from bs4 import BeautifulSoup
import json
import datetime
import time
import re
import sys

# TSE 業種コード → 業種名マッピング
SECTOR_MAP = {
    "1": "水産・農林業", "2": "鉱業", "3": "建設業", "4": "食料品",
    "5": "繊維製品", "6": "パルプ・紙", "7": "化学", "8": "医薬品",
    "9": "石油・石炭製品", "10": "ゴム製品", "11": "ガラス・土石製品",
    "12": "鉄鋼", "13": "非鉄金属", "14": "金属製品", "15": "機械",
    "16": "電気機器", "17": "輸送用機器", "18": "精密機器",
    "19": "その他製品", "20": "電気・ガス業", "21": "陸運業",
    "22": "海運業", "23": "空運業", "24": "倉庫・運輸関連業",
    "25": "情報・通信業", "26": "卸売業", "27": "小売業",
    "28": "銀行業", "29": "証券・商品先物取引業", "30": "保険業",
    "31": "その他金融業", "32": "不動産業", "33": "サービス業",
}

# 業種コード（数字）→ 略称マッピング（表示用）
SECTOR_CODE_TO_NAME = {
    "050": "水産・農林", "100": "鉱業", "150": "建設",
    "200": "食料品", "250": "繊維", "300": "パルプ・紙",
    "350": "化学", "400": "医薬品", "450": "石油・石炭",
    "500": "ゴム", "550": "ガラス・土石", "600": "鉄鋼",
    "650": "非鉄金属", "700": "金属製品", "750": "機械",
    "800": "電気機器", "850": "輸送用機器", "900": "精密機器",
    "950": "その他製品", "1000": "電気・ガス", "1050": "陸運",
    "1100": "海運", "1150": "空運", "1200": "倉庫・運輸",
    "1250": "情報・通信", "1300": "卸売", "1350": "小売",
    "1400": "銀行", "1450": "証券・先物", "1500": "保険",
    "1550": "その他金融", "1600": "不動産", "1650": "サービス",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_stop_high():
    """kabutan.jp からストップ高銘柄一覧を取得"""
    url = "https://kabutan.jp/warning/?mode=39&market=0"
    stocks = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # ストップ高テーブルを探す
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # ヘッダーをスキップ
                cols = row.find_all("td")
                if len(cols) < 5:
                    continue
                try:
                    # コード
                    code_td = cols[0]
                    code_link = code_td.find("a")
                    code = code_link.text.strip() if code_link else code_td.text.strip()

                    # 銘柄名
                    name_td = cols[1]
                    name_link = name_td.find("a")
                    name = name_link.text.strip() if name_link else name_td.text.strip()

                    # 市場・業種
                    market = cols[2].text.strip() if len(cols) > 2 else ""
                    sector = cols[3].text.strip() if len(cols) > 3 else "不明"

                    # 現在値
                    price_text = cols[4].text.strip().replace(",", "").replace("円", "")
                    price = float(price_text) if price_text and price_text != "-" else 0

                    # 前日比 / 変化率
                    change = cols[5].text.strip() if len(cols) > 5 else ""
                    change_pct = cols[6].text.strip() if len(cols) > 6 else ""

                    if code and name and price > 0:
                        stocks.append({
                            "code": code,
                            "name": name,
                            "market": market,
                            "sector": sector,
                            "price": price,
                            "change": change,
                            "change_pct": change_pct,
                            "stop_high": True,
                        })
                except (IndexError, ValueError, AttributeError):
                    continue

        if not stocks:
            stocks = fetch_stop_high_fallback()

    except Exception as e:
        print(f"[警告] メイン取得失敗: {e}", file=sys.stderr)
        stocks = fetch_stop_high_fallback()

    return stocks


def fetch_stop_high_fallback():
    """代替URL でストップ高を取得"""
    stocks = []
    # 代替ページ
    urls = [
        "https://kabutan.jp/warning/?mode=39&market=1",  # 東証
        "https://kabutan.jp/warning/?mode=39&market=3",  # 名証
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            # stock_table クラスのテーブル
            table = soup.find("table", class_=lambda c: c and "stock" in c.lower())
            if not table:
                # テーブルを全検索
                for t in soup.find_all("table"):
                    rows = t.find_all("tr")
                    if len(rows) > 3:
                        table = t
                        break

            if not table:
                continue

            rows = table.find_all("tr")
            for row in rows[1:]:
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue
                try:
                    code_text = cols[0].text.strip()
                    name_text = cols[1].text.strip()
                    if not re.match(r"^\d{4}$", code_text):
                        continue
                    price_text = re.sub(r"[^\d.]", "", cols[4].text.strip()) if len(cols) > 4 else "0"
                    price = float(price_text) if price_text else 0
                    sector = cols[3].text.strip() if len(cols) > 3 else "不明"
                    market = cols[2].text.strip() if len(cols) > 2 else ""
                    change = cols[5].text.strip() if len(cols) > 5 else ""
                    change_pct = cols[6].text.strip() if len(cols) > 6 else ""

                    stocks.append({
                        "code": code_text,
                        "name": name_text,
                        "market": market,
                        "sector": sector,
                        "price": price,
                        "change": change,
                        "change_pct": change_pct,
                        "stop_high": True,
                    })
                except (IndexError, ValueError):
                    continue

            time.sleep(1)

        except Exception as e:
            print(f"[警告] 代替取得失敗 ({url}): {e}", file=sys.stderr)

    return stocks


def fetch_top_gainers_japan():
    """kabutan.jp から上昇率上位銘柄を取得（補完用）"""
    url = "https://kabutan.jp/stock_kabuka/?mode=3&base=1&market=0"
    stocks = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.find("table", id="stock_table")
        if not table:
            tables = soup.find_all("table")
            for t in tables:
                if t.find("td") and len(t.find_all("tr")) > 5:
                    table = t
                    break

        if not table:
            return stocks

        rows = table.find_all("tr")
        for row in rows[1:51]:  # 上位50件
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            try:
                code_text = cols[0].text.strip()
                name_text = cols[1].text.strip()
                price_text = re.sub(r"[^\d.]", "", cols[3].text.strip())
                change_pct_text = re.sub(r"[^\d.+-]", "", cols[5].text.strip() if len(cols) > 5 else "")
                sector = cols[2].text.strip() if len(cols) > 2 else "不明"

                price = float(price_text) if price_text else 0
                stocks.append({
                    "code": code_text,
                    "name": name_text,
                    "market": "東証",
                    "sector": sector,
                    "price": price,
                    "change": "",
                    "change_pct": change_pct_text,
                    "stop_high": False,
                })
            except (IndexError, ValueError):
                continue
    except Exception as e:
        print(f"[警告] 上昇率取得失敗: {e}", file=sys.stderr)

    return stocks


def aggregate_by_sector(stocks):
    """業種別に集計"""
    sector_count = {}
    for s in stocks:
        sector = s.get("sector", "不明") or "不明"
        sector = sector.strip() or "不明"
        if sector not in sector_count:
            sector_count[sector] = {"count": 0, "stocks": []}
        sector_count[sector]["count"] += 1
        sector_count[sector]["stocks"].append(s["code"])
    # 件数降順ソート
    return dict(sorted(sector_count.items(), key=lambda x: x[1]["count"], reverse=True))


def main():
    print("日本株データ取得中...", file=sys.stderr)

    stop_high = fetch_stop_high()
    print(f"ストップ高: {len(stop_high)} 銘柄", file=sys.stderr)

    # ストップ高が少ない場合は上昇率上位も追加
    top_gainers = []
    if len(stop_high) < 5:
        print("上昇率上位銘柄を補完取得...", file=sys.stderr)
        top_gainers = fetch_top_gainers_japan()
        print(f"上昇率上位: {len(top_gainers)} 銘柄", file=sys.stderr)

    # 業種別集計
    sector_analysis = aggregate_by_sector(stop_high + top_gainers)

    output = {
        "updated_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
        "stop_high": stop_high,
        "top_gainers": top_gainers,
        "sector_analysis": sector_analysis,
        "total_stop_high": len(stop_high),
        "total_top_gainers": len(top_gainers),
    }

    out_path = "data/japan_stocks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"保存完了: {out_path}", file=sys.stderr)
    print(json.dumps({"status": "ok", "stop_high": len(stop_high)}))


if __name__ == "__main__":
    main()
