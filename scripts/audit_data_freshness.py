#!/usr/bin/env python3
"""公開データの件数・更新時刻・部分取得失敗を監査し data/health.json を生成する。"""

import argparse
import datetime
import json
import os
import sys


JST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(datetime.timezone.utc)

# name, file, list path, max age hours, minimum count, critical
DATASETS = [
    ("先物・為替", "futures.json", "items", 8, 3, True),
    ("日本株ランキング", "japan_stocks.json", "all_stocks", 36, 30, True),
    ("夜間PTSランキング", "pts_ranking.json", "all_stocks", 120, 10, False),
    ("市場のいま", "market_news.json", "items", 12, 5, True),
    ("日経225", "nikkei225.json", "items", 12, 100, True),
    ("テーマ株", "themes.json", "themes", 36, 3, True),
    ("日本株決算速報", "earnings_flash.json", "groups", 36, 1, False),
    ("出来高急増", "volume_stocks.json", "jp_stocks", 36, 1, False),
]


def parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def item_count(data, path):
    if path is None:
        return len(data.get("jp_stocks", [])) + len(data.get("us_stocks", []))
    value = data.get(path, [])
    return len(value) if isinstance(value, (list, dict)) else 0


def audit():
    results = []
    for name, filename, path, max_age, minimum, critical in DATASETS:
        full_path = os.path.join("data", filename)
        try:
            with open(full_path, encoding="utf-8") as f:
                data = json.load(
                    f,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"標準JSONではない値: {value}")
                    ),
                )
        except Exception as exc:
            results.append({
                "name": name, "file": filename,
                "status": "missing" if critical else "warning",
                "critical": critical, "message": f"読込失敗: {exc}",
            })
            continue

        updated = parse_time(data.get("updated_at"))
        age_hours = round((NOW - updated).total_seconds() / 3600, 1) if updated else None
        count = item_count(data, path)
        fetch_status = data.get("fetch_status", "ok")
        status = "ok"
        messages = []
        if count < minimum:
            status = "error" if critical else "warning"
            messages.append(f"件数不足（{count}/{minimum}）")
        if age_hours is None or age_hours > max_age:
            status = "error" if critical else "warning"
            messages.append(f"更新が古い（{age_hours if age_hours is not None else '不明'}時間）")
        if fetch_status == "stale":
            status = "error" if critical else "warning"
            messages.append(data.get("fetch_error") or "直近の取得に失敗")
        elif fetch_status in ("partial", "fallback") and status == "ok":
            status = "warning"
            messages.append(data.get("fetch_warning") or "代替・一部データで表示中")
        if filename == "volume_stocks.json":
            missing_markets = []
            if not data.get("jp_stocks"):
                missing_markets.append("日本株")
            if missing_markets and status == "ok":
                status = "warning"
                messages.append(f"{'・'.join(missing_markets)}の出来高データが未取得")

        results.append({
            "name": name,
            "file": filename,
            "status": status,
            "critical": critical,
            "updated_at": data.get("updated_at"),
            "last_attempt_at": data.get("last_attempt_at"),
            "age_hours": age_hours,
            "count": count,
            "source": data.get("source"),
            "scope": data.get("scope"),
            "fetch_status": fetch_status,
            "message": " / ".join(messages),
        })

    errors = [r for r in results if r["status"] in ("error", "missing") and r["critical"]]
    warnings = [r for r in results if r["status"] == "warning"]
    return {
        "checked_at": datetime.datetime.now(JST).isoformat(),
        "overall": "error" if errors else ("warning" if warnings else "ok"),
        "critical_errors": len(errors),
        "warnings": len(warnings),
        "healthy": len([r for r in results if r["status"] == "ok"]),
        "total": len(results),
        "datasets": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="重大な異常があれば終了コード1")
    parser.add_argument("--no-write", action="store_true", help="health.jsonを更新しない")
    args = parser.parse_args()

    report = audit()
    if not args.no_write:
        os.makedirs("data", exist_ok=True)
        with open("data/health.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "overall": report["overall"],
        "critical_errors": report["critical_errors"],
        "warnings": report["warnings"],
        "healthy": report["healthy"],
        "total": report["total"],
    }, ensure_ascii=False))
    for row in report["datasets"]:
        if row["status"] != "ok":
            print(f"  {row['status'].upper()}: {row['name']} - {row.get('message', '')}", file=sys.stderr)

    if args.strict and report["critical_errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
