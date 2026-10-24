# カウンセラー販売実績ダッシュボード 更新パイプライン

Netlify `naa-counselor`（https://naa-counselor.netlify.app）の「カウンセラー販売実績ダッシュボード」を、
Excel エクスポートではなく KOS OpenAPI から作り直す。Python 標準ライブラリだけで動く。

> **患者データはリポジトリに入れない。** API の生データ・生成した HTML は作業フォルダ（例 `/tmp/sales-work/counselor`、chmod 700）に置く。

## ファイル

| ファイル | 役割 |
|---|---|
| `fetch.py` | 統計クエリ（購入項目・予約・満足度調査。照合用に決済・施術タスク・プリペイド履歴も）を月ごとに取得して `WORK/raw/` に保存 |
| `aggregate.py` | 生データ → ページの `const D = {...}`（指標の定義はファイル冒頭） |
| `source.py` | `WORK/raw` を読んで `aggregate.build` に渡す。`export_gaps=True` で Excel 時代の欠損を再現 |
| `page.py` | HTML の `const D` の読み書きと、本文中の日付つきの文の更新 |
| `build.py` | 公開中の HTML ＋ API データ → 新しい HTML（D と日付の文だけ差し替え、CSS/JS は触らない） |
| `verify.py` | 公開中の HTML の数値を API から再計算して突き合わせる（`--table` で月別の対照表） |
| `check_render.js` | Chromium で全タブ × チャネル × 指標 × VOC 選択を表示し、JS エラーや NaN/undefined を検出 |

## 使い方

```bash
W=/tmp/sales-work/counselor; mkdir -p $W/out; chmod 700 $W
# 公開中のページ（パスワードなし）
python3 -I -c "import sys; sys.path.insert(0,'pipeline'); import netlify; netlify.download('naa-counselor', '$W/current.html')"

# 毎日（前日分まで）: 前月・当月を取り直して作り直す
python3 -I pipeline/sales/counselor/build.py --html $W/current.html --work $W --out $W/out/new.html --fetch
NODE_PATH=$(npm root -g) node pipeline/sales/counselor/check_render.js $W/out/new.html
python3 -I pipeline/sales/counselor/verify.py $W/out/new.html $W --strict     # 作ったページが API と一致するか

# 初回（全期間の取得、約8分）
python3 -I pipeline/sales/counselor/fetch.py $W 2026-03-20 2026-10-10
# Excel 時代の公開版との照合
python3 -I pipeline/sales/counselor/verify.py $W/current.html $W --export-gaps --table
```

- `build.py --until YYYY-MM-DD` で最終日を指定（省略時は前日 JST）。月が変わると `months`・月タブ・月次推移・VOC の月が自動で増える。
  データが少ない日（月初・休診日）でも動く（顧客0人の月も表示できることを確認済み）。
- 止まる条件: 最終日が今のページより前／締めた月（前月より前）のクリニック全体の顧客数が1%超・売上が2%超ずれる／
  今のページがまだ Excel エクスポート版（フッターに「エクスポート）」）。
- **初回の切り替えだけ** `--accept-closed-month-changes` を付ける（締めた月が変わることを受け入れる：9月の欠損補完、
  8月の返金反映、VOC の共用アカウント除外）。API 版のページに付けると止まるので、日次では使えない。
- 警告: 表示していないカウンセラーが当月5人以上を担当 → `aggregate.MAIN` と本文「表示するカウンセラー」の文に足すかを人が決める。
- 公開（Netlify deploy）はこのパイプラインではしない。

## 集計方針（2026-10-12 ユーザー決定）

- 共用アカウント（`data/staff_roles.csv` の備考に「集計から除外」）宛ての満足度評価・コメントは、クリニック全体の CS 満足度を含めて VOC から除く。
  会計は従来どおり（共用アカウント名義の会計はクリニック全体に含め、カウンセラー別には出さない）。
- VOC 全期間の「同期間の販売実績」（`VOCWIN`）は VOC の月すべて（8月〜当月）の合計。
- 「来院」件数は保留中。今は受付済みの予約の件数。

## 照合結果（2026-10-11、`verify.py --export-gaps --include-shared-voc`。Excel 版の集計方法での照合）

- クリニック全体の販売（顧客数・売上・プリペイド・コース・返金・施術数・値引後率・新規）: 3〜7月は全チャネルで完全一致。
  8月は売上 −105,000円・返金 +1人（エクスポート後に処理された返金）、9月は売上 −7,800円、10月は売上 +7,500円・施術 +1件（エクスポート後の修正）。
- VOC（全チャネル・各チャネル、カウンセラー別、コメント全件）: 8・9月と全期間で完全一致、10月は1人の回答者のチャネル（紹介/その他）だけ違う。
- カウンセラー別の販売: 担当の付け方の違いで1か月あたり ±1〜4人。5月は予約・会計に担当カウンセラーが入っていない行が多く、最大で売上 4.9% の差。
- 進行時間: 6〜8・10月は完全一致。3〜5月は API の予約にカウンセラー名がほとんど無く（5/28まで）、同じ日の会計担当で補っても 1〜13件少ない。
- クリニック全体の「来院」件数: 10月は一致、3〜9月は公開値が 4〜25% 多い（エクスポートの来院件数の数え方が API から再現できない）。

## 既知の欠損（Excel 時代の公開版）

9/24 10:16 以降の販売、9/24 の満足度調査（15件。ページには「欠損なく反映」とあった）、9/29・10/1・10/2 の来院。
API 版ではすべて埋まる（`build.py` が本文の「データの欠損」「データ源ごとの締め」の文も書き換える）。

## 週次の課題（ダッシュボード内の「週次の課題」セクション、パスワード保護）

カウンセラーごとの「良かった点・課題・来週やること」を、前週（月〜日）の実績から毎週書き直すセクション。
2026-10-16 は別サイト（naa-counselor-review）で始めたが、2026-10-24 にオーナーの決定で**このダッシュボードに合併**し、
naa-counselor を**パスワード保護**にした（個人名と課題が載るため。毎日の公開も保護を確認してから行う）。

```
python3 -I pipeline/sales/counselor/weekly_review.py prepare      # 数字 → $SALES_WORK/review/numbers.json と issues.json（ひな形）
#  -> issues.json を書く（下の指針）
python3 -I pipeline/sales/counselor/weekly_review.py finish       # 公開中のページに差し込み → 表示確認 → 公開（パスワード保護を確認してから）
```

| ファイル | 役割 |
|---|---|
| `weekly.py` | 前週と直前4週・クリニック全体の数字（このダッシュボードと同じ定義）。対象週の満足度調査の自由記述も入れる（ページには載せない材料） |
| `review_page.py` | セクションの HTML を作り、ページの `<!--WEEKLY:BEGIN-->`〜`<!--WEEKLY:END-->` を差し替える（初回は「カウンセラー別」の表の後に入れる）。全員分の課題が無い、週が合わない場合は止まる |
| `weekly_review.py` | prepare / finish。finish は公開中のページを取り、セクションだけ差し替えて `check_render.js` → `netlify.deploy`（保護が外れていたら止まる） |

毎日の `build.py` は `const D` の行と日付の文だけを書き換えるので、セクションはそのまま残る（週の途中で消えない）。

### issues.json の書き方（Claude が毎週書く）

```json
{"week": [月曜, 日曜], "updated": "YYYY-MM-DD 作成", "overview": "全体の2〜3文",
 "team": ["チーム全体の課題（2〜3個）"],
 "people": {"名前": {"headline": "一言", "good": ["…"], "issues": ["…"], "actions": ["…"]}}}
```

- 数字は numbers.json の値だけを使う（週と直前4週の比較、クリニック全体との比較）。推測しない。
- 1人につき good 1〜3、issues 1〜4、actions 1〜3。actions は来週すぐできる具体的な行動にする。
- 自由記述は要旨だけ書く（例:「少し早口という声」）。患者が特定できる内容・本文の長い引用・カルテ番号は書かない。
- 担当客数が10人未満の週（few）は、断定せず「件数が少ないので参考」と添える。
- 人を責める書き方にしない。課題は行動で書く（「〜が低い」だけで終わらせず、何をするかを actions に）。
