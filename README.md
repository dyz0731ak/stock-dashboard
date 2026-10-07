# 📊 投資の砦

日本株のストップ高・急騰銘柄・決算速報・テーマ株・市場ニュース・日経225ヒートマップを表示する定期更新型の投資ダッシュボード。海外市場は、日本株への影響を把握するための現物指数・為替・金スポット・重要ニュースに絞って掲載する。

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
| 🩺 鮮度監視 | 件数・更新時刻・部分取得失敗を `data/health.json` に記録。画面ではヘッダーと各セクションに取得状態を表示 |
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
- **日本株決算**: TDnetの日付付き一覧と原資料XBRL/PDF。規模を問わず利益変動・会社予想修正・増減配・自社株買いを選別。前年同期比と前回会社予想比を区別し、未取得の市場コンセンサスは推定しない。開示のない日は直近の発表日を明記して表示。

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
# 企業の一言説明と詳細

ランキングの企業名から企業詳細を開けます。東証・夜間PTS・ミニチャート・急騰銘柄の固定ページに対応。企業概要、関連テーマ、公式サイト、決算・開示へのリンクを表示します。

`scripts/fetch_company_profiles.py` はランキング掲載銘柄の企業基本情報を株探から取得し、株価とは別に `data/company_profiles.json` へ保存します。新規銘柄は追加取得、取得済みは週1回確認し、失敗時は前回成功時刻と説明を保全します。30日を超えた説明は表示しません。個別企業の取得失敗は他の企業や価格更新を止めず、`logs/company_profiles.log` に記録します。

`scripts/company_summaries.json` に読みやすく整えた一言説明を保持します。取得元の説明が変わった場合は編集済み文言を適用せず、新しい概要に切り替えます。

## 2026-09-25 指数カードの構成

上段に東証プライム市場指数・東証スタンダード市場指数・東証グロース市場指数、下段に日経225・NYダウ・NASDAQ総合指数・USD/JPY・SOX指数・金スポットを表示。大きな更新状態パネルは廃止し、取得状態はヘッダーと各セクションに表示する。

- `scripts/fetch_tse_indices.py` → `data/tse_indices.json`。JPX公開の `TseMarketType` から全市場の3指数を名前とキーで照合。JPXプライム150、スタンダードTOP20、グロース250には置き換えない。
- `scripts/fetch_market_indices.py` → `data/market_indices.json`。Yahoo Financeの `^N225` / `^DJI` / `^IXIC` / `JPY=X` / `^SOX` を使用。シンボル・商品種別を検証する。旧 `futures` 収集ジョブは定期実行から除外。
- 金は [Gold API](https://gold-api.com/docs) の `XAU` スポット（USD / トロイオンス）。無料の現在値APIに前日終値・履歴はないため、前日比は「—」。チャートは別取得元のXAU/USDスポットを使用し、その違いを明記する。先物やETFの値で代替しない。
- 各カードに出典リンクとデータ基準時刻（JST）を表示。取得時刻とは区別し、欠損・期限切れ時もカードの位置と名称を保って数値を非表示にする。
- 東証の値は取引日・市場時刻で検証。米国市場は休場を挟むため最大4日以内の基準時刻を許容し、カードに時刻を明記。全データは再取得から最大8時間で失効する。

追加検証: `python -m unittest discover -s tests -v`、`python scripts/prerender.py`、`python scripts/check_site.py`。

### 指標とチャートの取得

- Yahoo Finance生API→別ホスト→yfinanceの順。タイムアウト、HTTP 429/5xxの限定再試行、最大2並列。前回実値は取得時刻を変えず最大24時間保持し、「前回取得値」を表示。
- `fetch_market_history.py` は現物5指標のOHLCを1時間キャッシュし、銘柄×1/3/6/12/36ヶ月の静的JSONを生成。画面ではカードクリック・期間切替時だけ取得する。欠損OHLCを合成しない。
- 金チャートのみTradingView / ICEのXAU/USDスポットをオンデマンド埋め込み。カードのGold API価格とは取得元と時刻が異なる。
- `fetch_tse_history.py` はStockWeatherの全市場指数（0500/0501/0502）の実OHLCを取得し、JPXの指数名と時間外の最新四本値で照合。1・3ヶ月は日足、6ヶ月・1年は週足、3年は月足。提供元の長期足に続く部分は全営業日が揃った日足から集計し、不足区間は補間しない。1時間キャッシュ・限定リトライ・失敗時の前回データ保持に対応。画面の初期表示は1年、クリックした指数・期間のJSONだけ読み込む。
- 決算原資料の解析結果は `data/tdnet_cache.json` に8日保持。取得・解析失敗は6時間後に再試行。1件でも確認できた重要開示は掲載し、正常に確認できた0件と通信失敗を区別する。
- 決算の総額は `earnings_amounts.py` で統一。絶対額1億円以上は億円、未満は万円。実績・前回予想・修正後予想・比較文・キャッシュ済み文章にも適用し、1株配当やEPSだけ円を維持する。原資料の数値・単位は解析用に保存するが、百万円表記は画面へ出さない。

## TOPIX改革フィルター（2026-10-07公表版）

`index.html` の市場カラムの右に指数カラムを表示。東証／夜間PTSの現在の上位30件へ、TOPIX改革セレクトまたは文字バッジのクリックで条件を追加する。順位・並び順・株価は元ランキングのまま。市場・一覧／ミニチャート切替や毎分の株価更新でも条件を維持し、0件は該当なしと表示する。指数マスタ取得失敗時はフィルターを無効にして通常ランキングを表示し、取得済みマスタがある場合は基準日を維持して使用する。

### データと責務

- `data/index_memberships.json`: `securities[証券コード]` に `topix` / `topix_new` / `transition` / `nikkei225` の配列を保持。英字を含む4桁コードにも対応。同一銘柄は複数ラベルを持てる。銘柄名や市場区分から推定しない。
- `schema_version` は形式、`version` は公表版。`published_at` / `effective_at` / `reevaluation_at` と出典URL・原本SHA-256・区分別件数を記録。過去版はGit履歴に保持する。
- 今回のTOPIXは **2026-10-07公表の2026-10-30構成予定**。`topix` 1,669銘柄には `transition` 683銘柄、`topix_new` 35銘柄も含む。新規採用は実施前から改革情報として表示し、基準日と構成予定日を画面に明記する。「移行措置」を現在のTOPIX除外済みとは扱わない。
- 日経225は日経公式の2026-10-07更新一覧の225銘柄。ヒートマップの株価取得成否や既存の収集用リストから所属を推定せず、独立して保持。
- `index-memberships.js`: 純粋なコード正規化・所属判定・配列の交差抽出。`IndexMemberships.create(data).filter(rows, 'transition', row => row.code)` を出来高／決算／増配等にも再利用できる。既存の並べ替え・上位件数制限・絞り込みの後に適用する。
- `scripts/index_memberships.py`: 同じJSONを検証し、プリレンダリングと将来のPython側フィルターで使用。件数不一致や不正コードは採用しない。
- 既存の株価取得スクリプト・取得周期・JSON形式・株価鮮度判定は変更しない。ブラウザのマスタ確認は成功時1時間ごと、未取得時1分ごと。SSGにも同じ指数カラムを焼き込む。

公式資料: [JPX 2026-10-07発表](https://www.jpx.co.jp/news/6030/20261007-01.html)、[TOPIX選定結果・構成銘柄一覧](https://www.jpx.co.jp/news/6030/t13vrt00000262wd-att/topix_j.pdf)、[日経225構成銘柄](https://indexes.nikkei.co.jp/nkave/index/component?idx=nk225)。

### 対象変更時の更新

更新先は `data/index_memberships.json`。公式発表の新規・移行措置・構成銘柄、件数、公表日・適用日・出典を一緒に更新する。画面と判定処理の編集は不要。旧版と新版のコード差分をレビューしてから公開する。

現行形式のJPX PDFは `scripts/update_index_memberships.py` で取り込める。Popplerの `pdftotext` が必要。引数の件数は必ず新しい公式発表に合わせる。セクション・連番・重複・部分集合・件数を検証し、不一致なら元データを保持して終了する。将来PDF形式が変わった場合は `parse_topix_selection()` を新形式に合わせ、推定で補完しない。

```bash
python scripts/update_index_memberships.py \
  --pdf /path/to/topix_j.pdf \
  --published 2026-10-07 --effective 2026-10-30 --reevaluation 2027-10 \
  --announcement-url https://www.jpx.co.jp/news/6030/20261007-01.html \
  --document-url https://www.jpx.co.jp/news/6030/t13vrt00000262wd-att/topix_j.pdf \
  --new-count 35 --transition-count 683 --topix-count 1669
python -m unittest discover -s tests -v
node --test tests/index-memberships.test.cjs
python scripts/prerender.py
python scripts/check_site.py
```

日経225の入替は同JSONの `nikkei225` 所属・件数・`sources.nikkei.as_of`・出典・`basis_note` を公式一覧で更新する。上記JPX取込は日経225の所属を保持する。再評価時の移行措置解除も旧フラグの追加更新ではなく、その公表版の全区分を入れ替える。

ブラウザ検証はローカルHTTPサーバーを起動し、PlaywrightとChromeが利用可能な環境で `node tests/index-ranking.browser.cjs http://127.0.0.1:8765`。東証・PTSの5条件、クリック、順位、価格、ミニチャート、詳細、更新時維持、0件、マスタ不正、株価失効、31位混入防止、1440/768/390/320pxを確認する。テスト用時刻補正はブラウザ応答内だけで行い、保存データを変更しない。
