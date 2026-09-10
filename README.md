# 📊 投資の砦

日本株のストップ高・急騰銘柄・決算速報・テーマ株・市場ニュース・日経225ヒートマップを表示する定期更新型の投資ダッシュボード。海外市場は、日本株への影響を把握するための先物・為替・重要ニュースに絞って掲載する。

🔗 **ライブサイト**: https://dashboard.stock-overflow24.com/

## 機能

| 機能 | 説明 |
|------|------|
| 🇯🇵 日本株急騰ランキング | JPX公式の東証上場銘柄を母集団に、東証P/S/G横断の値上がり率上位30銘柄を表示 |
| 🌙 夜間PTSランキング | 進行中の夜間セッションは当日値を約定時刻付きで更新し、時間外は公式終了値を表示 |
| 🕯 6か月日足 | 急騰ランキング30銘柄をローソク足と出来高のミニチャートで表示 |
| ◆ 日本株決算 | 日本株の決算速報を表示 |
| ▦ 日本株ヒートマップ | 日経225銘柄を時価総額と騰落率で可視化 |
| ⏱ 自動更新 | GitHub Actions で**約15分おきに**データ更新（cron遅延あり） |
| 🩺 鮮度監視 | 件数・更新時刻・部分取得失敗を `data/health.json` に記録し、画面上にも表示 |
| 📄 決算PDF補完 | ニュースサイトが取得できない場合も、当日の原資料PDFから数値を抽出して重要決算を更新 |
| 📱 レスポンシブ | モバイル・タブレット対応 |

## 更新スケジュール

```
*/15 * * * *  (約15分おき。GitHub Actions cron は仕様上ベストエフォートで遅延することがあります)
```

## ファイル構成

```
stock-dashboard/
├── index.html                        # メインダッシュボード
├── data/
│   ├── japan_stocks.json             # 日本株ランキング・6か月日足（自動更新）
│   └── earnings_flash.json           # 日本株決算速報（自動更新）
├── scripts/
│   ├── fetch_japan_stocks.py         # JPX上場銘柄 × Yahoo Finance日足
│   └── requirements.txt             # Python 依存パッケージ
└── .github/workflows/
    └── update_stocks.yml             # GitHub Actions ワークフロー
```

## ローカル実行

```bash
pip install -r scripts/requirements.txt
python scripts/run_fetch.py japan_stocks --timeout 420
python scripts/audit_data_freshness.py
python scripts/prerender.py
python scripts/check_site.py
python -m unittest discover -s tests -v
```

## データソース

- **日本株母集団**: [JPX 上場銘柄一覧](https://www.jpx.co.jp/markets/statistics-equities/misc/01.html)
- **株価・日足**: Yahoo Finance（yfinance）
- **夜間PTS**: 進行中セッションは株探PTS夜間ランキング（ジャパンネクスト提供値）、終了後はジャパンネクスト公式CSV
- **日本株決算**: IRBANK・株探・決算プロ。前二者を取得できない場合は、決算プロ掲載の原資料PDFから売上・利益・増減率を補完

## ライセンス

MIT


## 2026-09 更新停止修正・監視室UI

- 停止原因: JPXの配布ファイルがxlsからxlsxに変更され固定URLが404に。楽天の全市場トップ10を30件必須の保存条件で拒否し、9月3日の値が残っていた。
- JPX配布ページからxls/xlsxリンクを解決、形式を検出して読み込む。銘柄マスタは1日キャッシュし、主取得失敗時に限り40日未満の検証済みマスタを利用。
- 東証ランキング: JPX/Yahoo全銘柄計算 → 市場日時を検証した株探モバイル上位30件 → 楽天P/S/G各10件を統合した全市場トップ10 → 日経225限定代替。対象範囲・件数・取得元を明示。95%未満の当日価格網羅率では全銘柄計算を採用せず、欠損があれば一部取得扱い。
- 取得日と取引日を分離。`fetched_at`/`last_success_at`は成功取得時刻、`last_attempt_at`は実際の取得試行、`session_date`/`as_of`は市場日・取得元の基準時刻。`health.checked_at`は監査時刻。`valid_until`で停止後も旧値の表示を終了。
- 国内現物の前後場・昼休み・祝日・年末年始と、PTSの17時〜翌6時（土曜早朝含む）を考慮。祝日はjpholiday使用。制度変更時はJPX/Japannext公式の営業日・取引時間と再照合する。
- Yahooの日足Closeが夜間にNaNとなる場合、同じ応答の`regularMarketPrice`を市場時刻・同一取引日で検証してヒートマップ/テーマの終値を補完。OHLCは捏造しない。補完できない旧値は除外。
- 各取得処理を別プロセス・時間上限で分離し、タイムアウトや例外でも残りの取得を継続。`logs/*.log`をActions成果物として14日保存。JSONへの失敗状態と前回値の保存を原子的に行う。
- プリレンダリング失敗・0件で以前のHTMLを残す問題を修正。静的ページにもデータ時刻と状態を記載し、古いランキング・数値を消す。既存URL、SEO・JSON-LD、姉妹サイトリンクは維持。
- メイン画面はダークネイビー/シアン、上昇赤・下落緑。毎分、各データを独立再確認。広告はAdSense公式パラメータ `data-overlays="collapsed-bottom"` で上部/展開型アンカーを抑制し、下部の通常アンカーに限定。広告管理画面側の全画面広告設定は変更していない。

### 障害確認

1. `data/health.json` の項目別状態・対象取引日・最終成功/試行時刻を確認。
2. Actionsの `fetch-logs-<run id>` にある当該ソースのHTTPエラー、解析エラー、取得件数、タイムアウトを確認。
3. `FORCE_RAKUTEN=1 python scripts/run_fetch.py japan_stocks --timeout 120` で10件の代替取得、`FORCE_KABUTAN=1`で30件の代替取得を実データ検証できる。強制指定は検証用で通常のActionsには設定しない。
4. 本番データで検証後に監査・プリレンダ・check_siteを実行。重大な欠損は公開状態を更新した後でジョブを失敗にする。

公式根拠: [JPX銘柄一覧](https://www.jpx.co.jp/markets/statistics-equities/misc/01.html)、[JPX休日](https://www.jpx.co.jp/corporate/about-jpx/calendar/)、[PTS取引時間](https://www.japannext.co.jp/ja/pts)、[AdSenseアンカー広告](https://support.google.com/adsense/answer/7478225?hl=ja)。
