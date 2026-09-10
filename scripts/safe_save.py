#!/usr/bin/env python3
"""
データ保存の安全ガード（共通モジュール）

目的:
  スクレイピングやAPI取得が一時的に失敗して「0件」になったとき、
  その空データで既存の正常なデータを上書きしてしまうのを防ぐ。

使い方:
  from safe_save import safe_save
  safe_save("data/xxx.json", new_data, lambda d: len(d.get("items", [])), label="市場ニュース")

挙動:
  - 新データの件数 > 0           → 通常どおり保存
  - 新データ0件 かつ 既存も0件   → 保存（初回など。害はない）
  - 新データ0件 かつ 既存 > 0件  → 保存スキップ。既存の良いデータを温存する
"""

import datetime
import json
import os
import sys


def _load_existing(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _write_json_atomic(path, data):
    """標準JSON以外のNaN/Infinityを拒否し、途中失敗で既存ファイルを壊さない。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def mark_failed(path, reason, attempted_at=None, details=None):
    attempted_at = attempted_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
    existing = _load_existing(path) or {}
    existing.update(last_attempt_at=attempted_at, fetch_status='stale', fetch_error=reason)
    if details:
        existing['last_failure'] = details
    _write_json_atomic(path, existing)
    print(json.dumps({'dataset':path, 'event':'fetch_failed', 'attempted_at':attempted_at,
                      'error':reason, 'retained_updated_at':existing.get('updated_at')}, ensure_ascii=False), file=sys.stderr)
    return False


def safe_save(path, new_data, count_fn, label="data", failure_reason=None):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    attempt = new_data.get('last_attempt_at') or now
    try:
        count = count_fn(new_data)
        json.dumps(new_data, allow_nan=False)
    except (ValueError, TypeError, KeyError) as exc:
        return mark_failed(path, f'JSON/validation: {type(exc).__name__}: {exc}', attempt)
    if count <= 0:
        return mark_failed(path, new_data.get('fetch_error') or failure_reason or
                           new_data.get('fetch_warning') or '取得結果が0件または必要件数未満', attempt,
                           {'source_attempts':new_data.get('source_attempts', [])})
    new_data.setdefault('fetch_status', 'ok')
    new_data.setdefault('last_attempt_at', attempt)
    new_data.setdefault('fetched_at', new_data.get('updated_at') or now)
    new_data.setdefault('last_success_at', new_data['fetched_at'])
    from data_status import stamp_data
    try:
        stamp_data(path, new_data)
    except (TypeError, ValueError) as exc:
        return mark_failed(path, f'data timestamp invalid: {exc}', attempt)
    if new_data.get('fetch_status') == 'stale':
        return mark_failed(path, new_data.get('fetch_error') or '取得元の日付・状態が不正', attempt)
    _write_json_atomic(path, new_data)
    print(json.dumps({'dataset':path, 'event':'saved', 'count':count,
                      'status':new_data['fetch_status'], 'fetched_at':new_data['fetched_at'],
                      'session_date':new_data.get('session_date')}, ensure_ascii=False), file=sys.stderr)
    return True
