#!/usr/bin/env python3
"""
注目銘柄（ウォッチリスト）の決算予定を生成するスクリプト。

方針:
  - 編集元は data/earnings_watchlist.json（手動）。銘柄の追加/削除はそこを編集するだけ。
  - 米国(us)の発表予定日は NASDAQ の決算カレンダー（api.nasdaq.com・無料/キー不要）から
    今後45日を前方スキャンしてベストエフォートで自動補完する。
    高頻度アクセスを避けるため、自動補完は REFRESH_HOURS 間隔でのみ実行（cron は5分毎でも軽量）。
  - 日本(jp)は同等の無料ソースが乏しいため date は手入力。空なら「日付未定」と表示。
  - 手動で date を入れた銘柄は、その値を自動補完より優先する。

出力: data/watchlist_earnings.json （フロントの「注目銘柄の決算予定」セクションが読む）
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

JST = datetime.timezone(datetime.timedelta(hours=9))
US_EASTERN = datetime.timezone(datetime.timedelta(hours=-4))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings?date={date}"

REFRESH_HOURS = 6          # 米国日付の自動補完間隔
SCAN_DAYS = 45             # 前方スキャンする最大日数（≒「近いうち」）

BASE = os.path.dirname(__file__)
WATCHLIST_PATH = os.path.normpath(os.path.join(BASE, "..", "data", "earnings_watchlist.json"))
OUT_REL = "data/watchlist_earnings.json"
OUT_PATH = os.path.normpath(os.path.join(BASE, "..", OUT_REL))


def us_time_label(nasdaq_time: str) -> str:
    """NASDAQ の time フィールド → 日本時間の目安ラベル。"""
    t = (nasdaq_time or "").lower()
    if "pre-market" in t or "before" in t:
        return "寄り前（日本時間 夜）"
    if "after-hours" in t or "after" in t:
        return "引け後（日本時間 翌朝）"
    return ""


def fetch_nasdaq_day(date_str: str) -> list[dict]:
    try:
        resp = requests.get(NASDAQ_URL.format(date=date_str), headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        return (resp.json().get("data") or {}).get("rows") or []
    except Exception as e:
        print(f"  [nasdaq] {date_str} エラー: {e}", file=sys.stderr)
        return []


def refresh_us_dates(tickers: set[str]) -> dict[str, dict]:
    """NASDAQ を前方スキャンして {ticker: {date, time_jst}} を返す（見つかった分だけ）。"""
    print(f"  [ウォッチリスト] 米国 {len(tickers)}銘柄の発表日を NASDAQ で前方スキャン...", file=sys.stderr)
    found: dict[str, dict] = {}
    today_et = datetime.datetime.now(US_EASTERN).date()
    remaining = set(tickers)

    for offset in range(0, SCAN_DAYS + 1):
        if not remaining:
            break
        d = today_et + datetime.timedelta(days=offset)
        if d.weekday() >= 5:   # 土日スキップ
            continue
        rows = fetch_nasdaq_day(d.strftime("%Y-%m-%d"))
        for r in rows:
            sym = (r.get("symbol") or "").strip().upper()
            if sym in remaining:
                found[sym] = {
                    "date": d.strftime("%Y-%m-%d"),
                    "time_jst": us_time_label(r.get("time")),
                }
                remaining.discard(sym)
        time.sleep(0.25)

    print(f"  [ウォッチリスト] 米国 {len(found)}/{len(tickers)}銘柄の発表日を取得", file=sys.stderr)
    return found


def compute_status(date_str: str, today: datetime.date) -> str:
    """発表前 / 発表済 / 日付未定 を返す。"""
    if not date_str:
        return "日付未定"
    try:
        d = datetime.date.fromisoformat(date_str)
    except ValueError:
        return "日付未定"
    return "発表済" if d < today else "発表前"


def load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> int:
    now_jst = datetime.datetime.now(JST)
    today = now_jst.date()

    watchlist = load_json(WATCHLIST_PATH)
    if not watchlist:
        print("[ウォッチリスト] earnings_watchlist.json が読めません。中止。", file=sys.stderr)
        return 1

    prior = load_json(OUT_PATH)
    prior_us_dates: dict[str, dict] = {
        s["ticker"]: {"date": s.get("auto_date", ""), "time_jst": s.get("auto_time_jst", "")}
        for s in prior.get("us", []) if s.get("ticker")
    }

    # ── 米国日付の自動補完（キャッシュが古いときだけ NASDAQ を叩く） ──
    refreshed_at = prior.get("dates_refreshed_at", "")
    do_refresh = True
    if refreshed_at:
        try:
            age_h = (now_jst - datetime.datetime.fromisoformat(refreshed_at)).total_seconds() / 3600
            do_refresh = age_h >= REFRESH_HOURS
            if not do_refresh:
                print(f"  [ウォッチリスト] 日付キャッシュ利用（{age_h:.1f}時間前）", file=sys.stderr)
        except Exception:
            do_refresh = True

    us_list = watchlist.get("us", [])
    tickers = {s["ticker"].upper() for s in us_list if s.get("ticker")}

    if do_refresh:
        auto = refresh_us_dates(tickers)
        if not auto and prior_us_dates:
            # 取得失敗 → 前回値を温存
            auto = prior_us_dates
            refreshed_at_out = refreshed_at or now_jst.isoformat()
        else:
            # 取得できなかった銘柄は前回値で補完
            for t in tickers:
                if t not in auto and prior_us_dates.get(t, {}).get("date"):
                    auto[t] = prior_us_dates[t]
            refreshed_at_out = now_jst.isoformat()
    else:
        auto = prior_us_dates
        refreshed_at_out = refreshed_at

    # ── 米国エントリ組み立て ──
    us_out = []
    for s in us_list:
        t = s["ticker"].upper()
        a = auto.get(t, {})
        manual_date = (s.get("date") or "").strip()
        manual_time = (s.get("time_jst") or "").strip()
        # 手動値を優先、無ければ自動値
        date_str = manual_date or a.get("date", "")
        time_jst = manual_time or a.get("time_jst", "")
        us_out.append({
            "ticker": s["ticker"],
            "name": s.get("name", s["ticker"]),
            "stars": s.get("stars", 3),
            "memo": s.get("memo", ""),
            "date": date_str,
            "time_jst": time_jst,
            "status": compute_status(date_str, today),
            "country": "US",
            # 次回リフレッシュ時のフォールバック用に自動値を保持
            "auto_date": a.get("date", ""),
            "auto_time_jst": a.get("time_jst", ""),
        })

    # ── 日本エントリ組み立て（手動 date のみ） ──
    jp_out = []
    for s in watchlist.get("jp", []):
        date_str = (s.get("date") or "").strip()
        jp_out.append({
            "code": s.get("code", ""),
            "name": s.get("name", ""),
            "stars": s.get("stars", 3),
            "memo": s.get("memo", ""),
            "date": date_str,
            "time_jst": (s.get("time_jst") or "").strip(),
            "status": compute_status(date_str, today),
            "country": "JP",
        })

    # 発表前を上に・日付の近い順、その中で★の多い順。日付未定は末尾。
    def sort_key(x):
        d = x["date"] or "9999-99-99"
        return (0 if x["status"] == "発表前" else 1 if x["status"] == "発表済" else 2, d, -x["stars"])
    us_out.sort(key=sort_key)
    jp_out.sort(key=sort_key)

    output = {
        "updated_at": now_jst.isoformat(),
        "dates_refreshed_at": refreshed_at_out,
        "us": us_out,
        "jp": jp_out,
        "summary": {"us_count": len(us_out), "jp_count": len(jp_out)},
    }

    safe_save(
        OUT_REL,
        output,
        lambda d: len(d.get("us", [])) + len(d.get("jp", [])),
        label="ウォッチリスト決算",
    )

    print(json.dumps({"status": "ok", "us": len(us_out), "jp": len(jp_out),
                      "refreshed": do_refresh}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
