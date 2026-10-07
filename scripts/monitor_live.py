#!/usr/bin/env python3
"""本番サイト（訪問者が実際に見ている側）の鮮度を監視する。

リポジトリ内の health.json が正常でも、デプロイが止まれば本番は古いまま。
そのため公開URLの data/health.json を直接読み、次を検出する:
  1. 本番の health.json 自体が古い → 収集またはデプロイが停止している
  2. 重大データセットが error/missing
  3. 取得失敗のまま長期間（LONG_STALE_HOURS 以上）放置されているデータセット
結果を Markdown で標準出力に出し、異常があれば終了コード1。
"""

import datetime
import json
import sys
import time
import urllib.request

LIVE_URL = "https://dashboard.stock-overflow24.com/data/health.json"
# 収集は約15分毎。GitHub cron の遅延を見込んでも75分更新が無ければ停止とみなす
MAX_LIVE_AGE_MINUTES = 75
# 週末・連休をまたいでも、これ以上の取得失敗は放置とみなす
LONG_STALE_HOURS = 72


def fetch_live_health():
    url = f"{LIVE_URL}?t={int(time.time())}"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "stock-dashboard-monitor"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_problems(health, now):
    problems = []
    checked = datetime.datetime.fromisoformat(health["checked_at"])
    age_min = (now - checked).total_seconds() / 60
    if age_min > MAX_LIVE_AGE_MINUTES:
        problems.append(
            f"本番の health.json が {age_min:.0f} 分更新されていません（収集ワークフローまたはデプロイが停止している疑い）"
        )
    for row in health.get("datasets", []):
        name, status = row.get("name"), row.get("status")
        age = row.get("age_hours")
        msg = row.get("message") or ""
        if status in ("error", "missing") and row.get("critical"):
            problems.append(f"重大: {name} が {status}（{msg}）")
        elif status != "ok" and age is not None and age >= LONG_STALE_HOURS:
            problems.append(f"長期取得失敗: {name} が {age:.0f} 時間更新されていません（{msg}）")
    return problems


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        health = fetch_live_health()
        problems = find_problems(health, now)
    except Exception as exc:
        health = None
        problems = [f"本番の health.json を取得できません: {exc}"]

    lines = [f"監視時刻: {now.astimezone(datetime.timezone(datetime.timedelta(hours=9))):%Y-%m-%d %H:%M} JST", ""]
    if problems:
        lines.append("## 検出された異常")
        lines += [f"- {p}" for p in problems]
    else:
        lines.append("異常なし")
    if health:
        lines += ["", "## 本番の各データ", "| データ | 状態 | 経過時間 | メモ |", "|---|---|---|---|"]
        for row in health.get("datasets", []):
            age = row.get("age_hours")
            lines.append(f"| {row.get('name')} | {row.get('status')} | {'' if age is None else f'{age}h'} | {row.get('message') or ''} |")
        lines.append(f"\n本番 health.json checked_at: {health.get('checked_at')}")
    print("\n".join(lines))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
