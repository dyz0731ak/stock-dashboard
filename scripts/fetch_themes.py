#!/usr/bin/env python3
"""
テーマ株ランキングを生成する（投資の森のテーマランキング相当）。

無料で「テーマ＋週間/月間騰落率＋勝率」を返すAPIは存在しないため、
キュレーションした「テーマ → 構成銘柄」マップをもとに、各銘柄の株価履歴から
テーマ単位の指標を自前計算する。

  - 前日比%      : 構成銘柄の前日比の平均
  - 1週間変動率  : 構成銘柄の「5営業日前→直近」騰落率の平均
  - 1ヶ月変動率  : 構成銘柄の「約21営業日前→直近」騰落率の平均
  - 勝率         : 週間でプラスだった構成銘柄の割合
  - 銘柄数       : 構成銘柄数
  - spark        : テーマ平均の正規化価格パス（ミニチャート用）

出力: data/themes.json
  {
    "updated_at": "...",
    "themes": [
      {"name": "半導体製造装置", "hot": true, "count": 5,
       "day_pct": 2.1, "week_pct": 8.4, "month_pct": 15.2, "win_rate": 80.0,
       "spark": [..], "top": [{"name":"レーザーテック","code":"6920","week_pct":12.3}, ...]},
      ...
    ]
  }

キャッシュ: themes_fetched_at を見て6時間キャッシュ（テーマ騰落は日次で十分）。
"""

import yfinance as yf
import pandas as pd
import json
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

JST = datetime.timezone(datetime.timedelta(hours=9))
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "themes.json")
CACHE_HOURS = 6

# ─────────────────────────────────────────────────────────────
# テーマ → 構成銘柄（コード, 銘柄名）。流動性の高い代表銘柄で構成。
# 追加・削除はここだけ編集すればよい。
# ─────────────────────────────────────────────────────────────
THEMES = {
    "半導体製造装置": [("8035", "東京エレクトロン"), ("6857", "アドバンテスト"), ("7735", "SCREEN"), ("6146", "ディスコ"), ("6920", "レーザーテック")],
    "半導体": [("6723", "ルネサス"), ("6963", "ローム"), ("4063", "信越化学"), ("3436", "SUMCO"), ("4004", "レゾナック")],
    "人工知能（AI）": [("9984", "ソフトバンクG"), ("3778", "さくらインターネット"), ("3993", "PKSHA"), ("4011", "ヘッドウォータース"), ("4488", "AIinside")],
    "防衛": [("7011", "三菱重工"), ("7012", "川崎重工"), ("7013", "IHI"), ("6208", "石川製作所"), ("6203", "豊和工業")],
    "量子コンピュータ": [("6702", "富士通"), ("6701", "NEC"), ("9432", "NTT"), ("3687", "フィックスターズ")],
    "電子部品": [("6981", "村田製作所"), ("6762", "TDK"), ("6971", "京セラ"), ("6976", "太陽誘電"), ("6594", "ニデック")],
    "ロボット": [("6954", "ファナック"), ("6506", "安川電機"), ("6861", "キーエンス"), ("6324", "ハーモニック")],
    "自動車": [("7203", "トヨタ自動車"), ("7267", "ホンダ"), ("7201", "日産自動車"), ("7269", "スズキ"), ("7270", "SUBARU")],
    "海運": [("9101", "日本郵船"), ("9104", "商船三井"), ("9107", "川崎汽船")],
    "銀行": [("8306", "三菱UFJ"), ("8316", "三井住友FG"), ("8411", "みずほFG"), ("8308", "りそなHD")],
    "総合商社": [("8058", "三菱商事"), ("8031", "三井物産"), ("8001", "伊藤忠商事"), ("8053", "住友商事"), ("8002", "丸紅")],
    "インバウンド": [("4661", "オリエンタルランド"), ("3099", "三越伊勢丹"), ("8233", "高島屋"), ("9020", "JR東日本")],
    "ゲーム": [("7974", "任天堂"), ("7832", "バンダイナムコ"), ("9697", "カプコン"), ("9684", "スクエニHD"), ("3635", "コーエーテクモ")],
    "不動産": [("8801", "三井不動産"), ("8802", "三菱地所"), ("8830", "住友不動産")],
    "高配当": [("2914", "JT"), ("9434", "ソフトバンク"), ("9433", "KDDI"), ("8058", "三菱商事"), ("5108", "ブリヂストン")],
    "蓄電池": [("6674", "GSユアサ"), ("6752", "パナソニックHD"), ("6504", "富士電機")],
    "鉄鋼": [("5401", "日本製鉄"), ("5411", "JFEHD"), ("5406", "神戸製鋼")],
    "空運": [("9202", "ANA"), ("9201", "JAL")],
    "医薬・バイオ": [("4519", "中外製薬"), ("4568", "第一三共"), ("4523", "エーザイ"), ("4502", "武田薬品")],
    "再生可能エネルギー": [("9519", "レノバ"), ("1407", "ウエストHD"), ("3150", "グリムス")],
}


def _series(df, ticker):
    """yf.download結果からティッカーのCloseシリーズを取り出す。"""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            s = df[ticker]["Close"]
        else:
            s = df["Close"]
        return s.dropna()
    except Exception:
        return pd.Series(dtype=float)


def main():
    # キャッシュ判定
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                prev = json.load(f)
            ts = prev.get("themes_fetched_at")
            if ts:
                age = (datetime.datetime.now(JST) - datetime.datetime.fromisoformat(ts)).total_seconds()
                if age < CACHE_HOURS * 3600:
                    print(f"  ⏭ テーマ: {age/3600:.1f}h前に取得済み（{CACHE_HOURS}hキャッシュ）→ スキップ", file=sys.stderr)
                    return
        except Exception:
            pass

    # 全ユニークティッカーを一括ダウンロード
    code_name = {}
    for members in THEMES.values():
        for code, name in members:
            code_name[code] = name
    tickers = [f"{c}.T" for c in code_name]
    print(f"  テーマ {len(THEMES)}件 / 銘柄 {len(tickers)}件 をダウンロード中…", file=sys.stderr)

    df = yf.download(tickers, period="3mo", interval="1d",
                     group_by="ticker", auto_adjust=True, threads=True, progress=False)

    # 各銘柄の指標を計算
    stock_metrics = {}
    for code in code_name:
        s = _series(df, f"{code}.T")
        if len(s) < 6:
            continue
        last = float(s.iloc[-1])
        prev_c = float(s.iloc[-2])
        wk = float(s.iloc[-6]) if len(s) >= 6 else float(s.iloc[0])
        mo = float(s.iloc[-22]) if len(s) >= 22 else float(s.iloc[0])
        stock_metrics[code] = {
            "day": (last / prev_c - 1) * 100 if prev_c else 0,
            "week": (last / wk - 1) * 100 if wk else 0,
            "month": (last / mo - 1) * 100 if mo else 0,
            "path": [float(x) for x in s.iloc[-22:].tolist()],
        }

    themes_out = []
    for name, members in THEMES.items():
        ms = [(code, nm, stock_metrics[code]) for code, nm in members if code in stock_metrics]
        if not ms:
            continue
        n = len(ms)
        day = sum(m["day"] for _, _, m in ms) / n
        week = sum(m["week"] for _, _, m in ms) / n
        month = sum(m["month"] for _, _, m in ms) / n
        win = sum(1 for _, _, m in ms if m["week"] > 0) / n * 100
        # テーマ平均の正規化スパーク（各銘柄を起点100に正規化して平均）
        L = min(len(m["path"]) for _, _, m in ms)
        spark = []
        if L >= 2:
            for i in range(L):
                vals = [m["path"][-L + i] / m["path"][-L] * 100 for _, _, m in ms]
                spark.append(round(sum(vals) / n, 2))
        top = sorted(
            [{"name": nm, "code": code, "week_pct": round(m["week"], 2)} for code, nm, m in ms],
            key=lambda x: -x["week_pct"],
        )[:4]
        themes_out.append({
            "name": name, "count": n,
            "day_pct": round(day, 2), "week_pct": round(week, 2),
            "month_pct": round(month, 2), "win_rate": round(win, 1),
            "spark": spark, "top": top,
        })

    # 週間騰落率で降順（=上昇ランキング）。hot = 週間が上位 or +5%以上
    themes_out.sort(key=lambda t: -t["week_pct"])
    for i, t in enumerate(themes_out):
        t["hot"] = (i < 2) or (t["week_pct"] >= 5.0)

    out = {
        "updated_at": datetime.datetime.now(JST).isoformat(),
        "themes_fetched_at": datetime.datetime.now(JST).isoformat(),
        "themes": themes_out,
    }
    safe_save(OUT, out, lambda d: len(d.get("themes", [])), label="テーマ株")


if __name__ == "__main__":
    main()
