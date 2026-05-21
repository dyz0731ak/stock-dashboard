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


def safe_save(path, new_data, count_fn, label="data"):
    """
    取得失敗（0件）で既存データを破壊しないようガードしつつ JSON 保存する。

    Args:
        path:     保存先パス
        new_data: 保存したいdict
        count_fn: dictを受け取り「件数」を返す関数
        label:    ログ表示用ラベル

    Returns:
        True  = 保存した
        False = スキップした（既存データを温存）
    """
    try:
        new_count = count_fn(new_data)
    except Exception:
        new_count = 0

    existing = _load_existing(path)
    old_count = 0
    if existing is not None:
        try:
            old_count = count_fn(existing)
        except Exception:
            old_count = 0

    # 取得失敗 → 既存の良いデータを温存
    if new_count == 0 and old_count > 0:
        print(
            f"  ⚠ [{label}] 取得結果0件 → 既存データ{old_count}件を温存（上書きスキップ）",
            file=sys.stderr,
        )
        return False

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print(f"  ✓ [{label}] 保存: {path}（{new_count}件）", file=sys.stderr)
    return True
