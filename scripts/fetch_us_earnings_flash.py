#!/usr/bin/env python3
"""
米国株 決算速報（EPSサプライズ）取得スクリプト

データソース:
  api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
    — 当日に決算発表した米国企業の EPS実績 / EPS予想 / サプライズ% を返すJSON。

日本株版（fetch_earnings_flash.py）と同じJSONスキーマで出力するため、
フロントの決算速報レンダラ（renderEarningsFlash）をそのまま再利用できる。

注意（鮮度と正確性のトレードオフ）:
  Nasdaq の `surprise` 列は発表当日はまだ "N/A" で、翌営業日に数値が確定する。
  確定前の当日分は `eps`(実績) が GAAP/非GAAP の取り違えで全面ミスに見える等の
  ノイズが出やすいので、本スクリプトは「surprise が数値で確定している直近営業日」
  を採用する（＝約1営業日遅れだが内容は正確）。

出力: data/earnings_flash_us.json
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
from typing import Any

import requests

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

JST = datetime.timezone(datetime.timedelta(hours=9))
# 米国東部（5月はEDT=UTC-4）。日付の概算にしか使わないので固定でよい。
US_EASTERN = datetime.timezone(datetime.timedelta(hours=-4))

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings?date={date}"

# サプライズ% → カテゴリ（しきい値）
#   s >= 15            大幅上振れ
#   1.5 < s < 15       上振れ
#   -1.5 <= s <= 1.5   ほぼ予想通り
#   -15 < s < -1.5     下振れ
#   s <= -15           大幅下振れ
CATEGORY_META: dict[str, dict] = {
    "大幅上振れ": {"priority": 10, "zone": "positive", "suffix": "の大幅上振れ"},
    "上振れ":     {"priority": 20, "zone": "positive", "suffix": "で上振れ"},
    "ほぼ予想通り": {"priority": 60, "zone": "decision", "suffix": "でほぼ予想通り"},
    "下振れ":     {"priority": 80, "zone": "negative", "suffix": "で下振れ"},
    "大幅下振れ": {"priority": 85, "zone": "negative", "suffix": "の大幅下振れ"},
}


def classify(surprise: float) -> str:
    if surprise >= 15:
        return "大幅上振れ"
    if surprise > 1.5:
        return "上振れ"
    if surprise >= -1.5:
        return "ほぼ予想通り"
    if surprise > -15:
        return "下振れ"
    return "大幅下振れ"


def call_time_label(t: str) -> str:
    """Nasdaqの time フィールドを日本語の短いラベルに"""
    t = (t or "").lower()
    if "pre-market" in t or "before" in t:
        return "寄り前"
    if "after-hours" in t or "after" in t:
        return "引け後"
    return ""


_NUM_RE = re.compile(r"-?\$?\s*-?\d[\d,]*\.?\d*")


def parse_money(s: str | None) -> float | None:
    """'$4.28' / '($0.30)' / '-$0.5' → float（取れなければ None）"""
    if not s or s in ("N/A", "-", ""):
        return None
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")  # 会計表記の負値
    m = _NUM_RE.search(s.replace("(", "-").replace(")", ""))
    if not m:
        return None
    try:
        v = float(m.group(0).replace("$", "").replace(",", "").replace(" ", ""))
    except ValueError:
        return None
    return -abs(v) if neg else v


def parse_surprise(s: str | None) -> float | None:
    if not s or s in ("N/A", "-", ""):
        return None
    try:
        return float(str(s).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None


def parse_market_cap(s: str | None) -> float:
    """'$445,289,617,873' → 445289617873.0（取れなければ 0）"""
    if not s or s in ("N/A", "-", ""):
        return 0.0
    try:
        return float(re.sub(r"[^\d.]", "", str(s)) or 0)
    except ValueError:
        return 0.0


# 極小銘柄（SPAC・名証/店頭の超小型など）はサプライズ%が極端に出やすく
# ノイズになるため、時価総額がこの値未満の銘柄は除外する。
MIN_MARKET_CAP = 3.0e8  # 3億ドル


def fmt_cap(cap: float) -> str:
    """時価総額を短い日本語表記に（チップ用）"""
    if cap >= 1e12:
        return f"時価総額 ${cap / 1e12:.1f}兆"
    if cap >= 1e9:
        return f"時価総額 ${cap / 1e9:.0f}B"
    if cap >= 1e6:
        return f"時価総額 ${cap / 1e6:.0f}M"
    return ""


def fetch_day(date_str: str) -> list[dict]:
    url = NASDAQ_URL.format(date=date_str)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"  [nasdaq] {date_str} status={resp.status_code}", file=sys.stderr)
            return []
        rows = (resp.json().get("data") or {}).get("rows") or []
    except Exception as e:
        print(f"  [nasdaq] {date_str} エラー: {e}", file=sys.stderr)
        return []
    return rows


def build_items(rows: list[dict]) -> list[dict]:
    """surprise が数値で確定している行のみをリッチエントリ化"""
    items: list[dict] = []
    for r in rows:
        surprise = parse_surprise(r.get("surprise"))
        if surprise is None:
            continue  # 当日未確定の行は除外（ノイズ回避）
        symbol = (r.get("symbol") or "").strip()
        if not symbol:
            continue
        cap = parse_market_cap(r.get("marketCap"))
        # 時価総額が判明していて閾値未満の極小銘柄は除外（ノイズ回避）
        if 0 < cap < MIN_MARKET_CAP:
            continue
        actual = parse_money(r.get("eps"))
        forecast = parse_money(r.get("epsForecast"))
        cat = classify(surprise)
        meta = CATEGORY_META[cat]

        sign = "+" if surprise > 0 else ""
        actual_s = (r.get("eps") or "").strip()
        fc_s = (r.get("epsForecast") or "").strip()

        # ナラティブ: 「EPS実績 $3.05 / 予想 $2.30（+32.6%）で大幅上振れ」
        parts = []
        if actual_s and actual_s != "N/A":
            parts.append(f"EPS実績 {actual_s}")
        if fc_s and fc_s != "N/A":
            parts.append(f"予想 {fc_s}")
        head = " / ".join(parts) if parts else "EPS"
        narrative = f"{head}（{sign}{surprise:.1f}%）{meta['suffix']}"

        direction = "up" if surprise > 0 else "down" if surprise < 0 else "up"
        strong = abs(surprise) >= 15
        chips = [
            {
                "label": "サプライズ",
                "value": f"{sign}{surprise:.1f}%",
                "direction": direction,
                "strength": "strong" if strong else "normal",
                "pct": abs(surprise),
            }
        ]
        if actual is not None and actual_s and actual_s != "N/A":
            chips.append(
                {
                    "label": "実績",
                    "value": actual_s,
                    "direction": direction,
                    "strength": "normal",
                    "pct": abs(surprise),
                }
            )

        items.append(
            {
                "code": symbol,
                "name": (r.get("name") or "").strip(),
                "time": call_time_label(r.get("time")),
                "category": cat,
                "narrative": narrative,
                "narrative_source": "nasdaq",
                "metrics": {
                    "eps_actual": actual_s,
                    "eps_forecast": fc_s,
                    "surprise_pct": surprise,
                    "market_cap": cap,
                },
                "chips": chips,
                "sources": ["nasdaq"],
                "primary_source": "nasdaq",
                # 並び順は「注目される＝時価総額の大きい順」。フロントの
                # renderEarningsFlash は sort_val 降順で並べる（無い銘柄は時刻順）。
                "sort_val": cap,
                "url": f"https://finance.yahoo.com/quote/{symbol}",
            }
        )
    return items


def group_items(items: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["category"], []).append(it)
    # 各グループ内は時価総額の大きい順（注目銘柄を上に）
    for lst in groups.values():
        lst.sort(key=lambda x: x.get("sort_val", 0), reverse=True)

    out = []
    for cat, lst in groups.items():
        meta = CATEGORY_META[cat]
        out.append(
            {
                "category": cat,
                "display": cat,
                "priority": meta["priority"],
                "zone": meta["zone"],
                "items": lst,
            }
        )
    out.sort(key=lambda g: g["priority"])
    return out


def main() -> int:
    now_jst = datetime.datetime.now(JST)
    now_et = datetime.datetime.now(US_EASTERN).date()
    print(f"[米国決算速報] {now_jst.isoformat()} 実行開始（ET基準日={now_et}）", file=sys.stderr)

    # 当日(ET)は surprise 未確定が多いので、確定済みの直近営業日を探す。
    # 最大7日さかのぼり、surprise数値が5件以上ある最初の日を採用。
    chosen_date = ""
    chosen_rows: list[dict] = []
    for back in range(0, 8):
        d = now_et - datetime.timedelta(days=back)
        if d.weekday() >= 5:  # 土日スキップ
            continue
        rows = fetch_day(d.strftime("%Y-%m-%d"))
        n_settled = sum(1 for r in rows if parse_surprise(r.get("surprise")) is not None)
        print(f"  [nasdaq] {d}: rows={len(rows)} surprise確定={n_settled}", file=sys.stderr)
        if n_settled >= 5:
            chosen_date = d.strftime("%Y-%m-%d")
            chosen_rows = rows
            break
        time.sleep(0.3)

    items = build_items(chosen_rows)
    groups = group_items(items)
    total = sum(len(g["items"]) for g in groups)

    data: dict[str, Any] = {
        "updated_at": now_jst.isoformat(),
        "article_date": chosen_date,
        "market": "us",
        "sources": ["nasdaq"],
        "source_counts": {"nasdaq": len(chosen_rows)},
        "groups": groups,
        "total": total,
    }

    out_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "earnings_flash_us.json")
    )
    print(
        f"[米国決算速報] 採用日={chosen_date} total={total} groups={len(groups)}",
        file=sys.stderr,
    )
    safe_save(out_path, data, lambda d: d.get("total", 0), label="米国決算速報")
    return 0


if __name__ == "__main__":
    sys.exit(main())
