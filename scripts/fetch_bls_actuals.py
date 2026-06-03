#!/usr/bin/env python3
"""
米国 主要経済指標の「結果値（actual）」を BLS（米労働統計局）公式APIから取得する。

ForexFactory の週次フィードには結果値が無いため、雇用・物価の一次ソースである
BLS から取得して補完する。BLS Public Data API v2 は API キー不要で利用可
（未登録は 1日25クエリ・10年範囲まで。全シリーズを1回のPOSTでまとめて取得する）。

カバー指標（FFの表示単位に合わせて変換）:
  - 失業率                         : LNS14000000   （水準 %）
  - 雇用統計（非農業部門雇用者数）  : CES0000000001 （前月差・千人 → "85K"）
  - 平均時給（前月比）             : CES0500000003 （前月比 %）
  - CPI（消費者物価指数）          : CUSR0000SA0    （前月比 %）
  - コアCPI                        : CUSR0000SA0L1E （前月比 %）

出力: data/bls_actuals.json
  {
    "updated_at": "...",
    "actuals": {
      "失業率": {"value": "4.4%", "period": "2025-12", "series": "LNS14000000"},
      ...
    }
  }

これを fetch_events.py が読み、発表済みの米国指標に「結果値」を埋める
（イベントの参照月＝発表月の前月 と BLS の period が一致したときのみ）。
"""

import requests
import json
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

JST = datetime.timezone(datetime.timedelta(hours=9))
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "bls_actuals.json")
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CACHE_HOURS = 6

# series_id → 表示マッピング（ja は IMPORTANT_INDICATORS の ja と一致させる）
BLS_SERIES = {
    "LNS14000000":    {"ja": "失業率",                       "transform": "level_pct"},
    "CES0000000001":  {"ja": "雇用統計（非農業部門雇用者数）", "transform": "mom_change_k"},
    "CES0500000003":  {"ja": "平均時給（前月比）",            "transform": "mom_pct"},
    "CUSR0000SA0":    {"ja": "CPI（消費者物価指数）",         "transform": "mom_pct"},
    "CUSR0000SA0L1E": {"ja": "コアCPI",                      "transform": "mom_pct"},
}


def _fmt(transform, latest, prev):
    lv = float(latest)
    if transform == "level_pct":
        return f"{lv:.1f}%"
    pv = float(prev)
    if transform == "mom_change_k":
        return f"{lv - pv:.0f}K"          # 千人単位の前月差（FF表記に合わせ符号は負のみ）
    if transform == "mom_pct":
        return f"{(lv / pv - 1) * 100:.1f}%"
    return str(lv)


def main():
    # キャッシュ判定
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
            ts = prev.get("updated_at")
            if ts:
                age = (datetime.datetime.now(JST) - datetime.datetime.fromisoformat(ts)).total_seconds()
                if age < CACHE_HOURS * 3600:
                    print(f"  ⏭ BLS結果値: {age/3600:.1f}h前に取得済み → スキップ", file=sys.stderr)
                    return
        except Exception:
            pass

    this_year = datetime.date.today().year
    print("  [結果値] BLS API から米国指標を取得中...", file=sys.stderr)
    try:
        resp = requests.post(
            BLS_URL,
            json={
                "seriesid": list(BLS_SERIES.keys()),
                "startyear": str(this_year - 1),
                "endyear": str(this_year),
            },
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        payload = resp.json()
    except Exception as e:
        print(f"  ⚠ [結果値] BLS取得失敗: {e}", file=sys.stderr)
        return

    if payload.get("status") != "REQUEST_SUCCEEDED":
        print(f"  ⚠ [結果値] BLS status={payload.get('status')} {payload.get('message')}", file=sys.stderr)
        return

    actuals = {}
    for s in payload.get("Results", {}).get("series", []):
        sid = s["seriesID"]
        cfg = BLS_SERIES.get(sid)
        if not cfg:
            continue
        # 月次データのみ（M01〜M12）。data は新しい順。
        rows = [r for r in s.get("data", []) if r.get("period", "").startswith("M")
                and r["period"] != "M13" and r.get("value") not in (None, "", "-")]
        if len(rows) < 2:
            continue
        latest, prev = rows[0], rows[1]
        period = f"{latest['year']}-{int(latest['period'][1:]):02d}"
        actuals[cfg["ja"]] = {
            "value": _fmt(cfg["transform"], latest["value"], prev["value"]),
            "period": period,
            "series": sid,
        }

    out = {"updated_at": datetime.datetime.now(JST).isoformat(), "actuals": actuals}
    safe_save(OUT, out, lambda d: len(d.get("actuals", {})), label="BLS結果値")


if __name__ == "__main__":
    main()
