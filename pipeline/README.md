# 4職種横断ダッシュボード 更新パイプライン

KOSの「満足度調査（来院後満足度調査アンケート）」の回答をKOS OpenAPIから取得し、
claude.ai に公開している「4職種横断ダッシュボード」の **当月タブ** と **全期間タブ** を作り直すための手順とプログラムです。

- 公開先: https://claude.ai/artifact/CoeZYkHe1oLTNLmXxvTNSY（非公開。本人と共有相手のみ閲覧可）
- 初回実行: 2026-10-11（10/1〜10/11提出の209件を反映）

> **患者データはリポジトリに入れない。**
> APIの生データ（氏名・生年月日・カルテ番号を含む）、コメント本文、分類作業ファイル、生成したHTMLは、
> すべてセッションの scratchpad など **リポジトリの外** に置く。`pipeline/.gitignore` でも主なファイル名を除外している。

## ファイル

| ファイル | 役割 |
|---|---|
| `kos_client.py` | APIキーをトークンに交換し、満足度調査の回答を期間指定で取得する |
| `aggregate.py` | 回答 → 数値ブロック（職種スコア・ドライバー・担当者別・時間帯・曜日・属性）の集計、コメント抽出 |
| `copytext.py` | 横断サマリーと、各職種の見出し・説明文の生成 |
| `html_payload.py` | ダッシュボードHTMLに埋め込まれたJSON（`<script id="payload">`）の読み書き |
| `prepare_labels.py` | ダッシュボードにまだ入っていない回答を抜き出し、コメント分類用の作業ファイルを作る |
| `build.py` | 当月と全期間を作り直したHTMLを出力する |
| `verify.py` | 既存の月を再計算し、ダッシュボードと一致するか確認する |
| `daily.py` | 毎日の自動更新（取得〜公開まで。下記） |
| `netlify.py` | Netlifyの現行ページの取得と公開（パスワード保護が外れていたら公開しない） |
| `check_render.js` | ダッシュボードをChromiumで開き、全タブを切り替えてエラーがないか確認する |
| `role_dashboards.py` | 職種別ダッシュボード4種（受付／看護師／医師／カウンセラーとクリニック総評）を4職種横断の新データで更新する |
| `../data/staff_roles.csv` | スタッフ名と職種の対応表（施術評価の医師／看護師の振り分けに使う） |

## 前提

- 環境変数 `EHR_API_KEY`: KOS OpenAPIのAPIキー（KOSチーム発行）。チャットやリポジトリには書かない。
- ネットワーク: `open-api.kos-solution.com` への通信が許可されていること。
- Python 3 の標準ライブラリだけで動く（追加インストール不要）。

## 毎日の自動更新（Netlify）

毎日 0:00（JST）にClaude Codeの定期実行（ルーティン）が、前日提出分までをNetlifyの5サイトに反映する。

| サイト | 中身 |
|---|---|
| https://naaclinic-all-voc.netlify.app | 4職種横断ダッシュボード（**これが最新版の正本**。毎回ここから読み込んで作り直す） |
| https://naaclinic-rc.netlify.app | 受付とクリニック総評 |
| https://naaclinic-cs.netlify.app | カウンセラーとクリニック総評 |
| https://naaclinic-dr.netlify.app | 医師とクリニック総評 |
| https://naaclinic-ns.netlify.app | 看護師とクリニック総評 |

```bash
python3 -I pipeline/daily.py prepare          # Netlifyから現行版、KOSから全月を取得 → 締めた月の再現チェック → 未反映の回答を抽出
# $WORK/todo_*.json の各コメントに t / p、輝いていたスタッフに shine を記入（下の「コメント分類のルール」）
python3 -I pipeline/daily.py finish           # 作り直し → 職種別4ページ → ブラウザ表示チェック → 5サイトに公開
```

- `--date YYYY-MM-DD` で反映する最終提出日を指定できる（省略時は前日）。すでに反映済みなら `NOTHING TO DO` で終わる。
- 作業フォルダ `$WORK`（既定 `/tmp/survey-work`）には患者データが入る。リポジトリの外に置く。
- 前提: 環境変数 `EHR_API_KEY`・`NETLIFY_AUTH_TOKEN`、通信許可 `open-api.kos-solution.com`・`api.netlify.com`、Chromium（`/opt/pw-browsers`）とグローバルの `playwright`。
- 次のどれかに当たると **公開せずに止まる**: 締めた月の数値・説明文が再現しない／分類漏れ／回答数・自由記述数が前回より減る／ブラウザでエラーや「NaN」「undefined」が出る／サイトのパスワード保護が外れている。
- 月が変わると新しい月のタブ（`periodList`・各職種・横断サマリー・月別推移）を自動で追加する。前月の最終日分が未反映なら、先に前月を締めてから新しい月を作る。
- 月初で件数が少ないうちは、担当者別・属性別・時間帯の説明文を「件数がたまってから表示」の文面にし、時間帯は表で表示する（`hoursSparse`：1時間あたり最大8件未満）。
- 「総評★3以下の回」（`lowClinic`）はAPIデータから毎回作り直す（8〜10月の既存リストと並び順まで一致を確認済み）。
- claude.ai の公開ページ（Artifact）は自動更新しない。Netlifyが正本。

## 手動での更新手順（参考）

作業フォルダは scratchpad（例: `$W`）にする。以下は 2026-10-11 分を反映したときの例。

```bash
W=/path/to/scratchpad/kos   # リポジトリの外
# 1. 公開中のダッシュボードを取得（Claude の Artifact read で保存し、そのファイルを $W/current.html にコピー）

# 2. KOSから回答を取得（月ごと・JSTの日付境界 = 前日15:00Z）
python3 -I pipeline/kos_client.py 2026-08-10T15:00:00Z 2026-08-31T15:00:00Z $W/raw_aug.json
python3 -I pipeline/kos_client.py 2026-08-31T15:00:00Z 2026-09-30T15:00:00Z $W/raw_sep.json
python3 -I pipeline/kos_client.py 2026-09-30T15:00:00Z 2026-10-11T15:00:00Z $W/raw_oct.json

# 3. 集計方法がずれていないか確認（締めた月で全部 OK になること）
python3 -I pipeline/verify.py $W/current.html aug 8月 $W/raw_aug.json
python3 -I pipeline/verify.py $W/current.html sep 9月 $W/raw_sep.json

# 4. 未反映の回答を抜き出す → $W/todo.json の各コメントに t / p、輝いていたスタッフに shine を記入
python3 -I pipeline/prepare_labels.py $W/current.html oct $W/todo.json $W/raw_oct.json

# 5. HTMLを作り直す
python3 -I pipeline/build.py --html $W/current.html --period oct --label 10月 \
  --month $W/raw_oct.json --all $W/raw_aug.json $W/raw_sep.json $W/raw_oct.json \
  --labels $W/todo.json --sub-to 2026-10-11 --out $W/dashboard.html

# 6. ブラウザで全タブを表示してエラーがないか確認し、Artifact publish（url を指定）で同じURLに公開

# 7. 職種別ダッシュボード4種も更新（元のHTMLは claude.ai プロジェクトのチャットから書き出したもの）
python3 -I pipeline/role_dashboards.py $W/dashboard.html $W/roles $W/role_src/*.html
```

職種別ダッシュボードの `periods[期間]` は、4職種横断の `roles[職種].periods[期間]` と完全に同じデータ
（2026-10-11 に全職種・全期間で一致を確認）。そのため職種別は集計し直さず、4職種横断の結果をコピーするだけでよい。

`build.py` は分類漏れ（`t` が空、`p` が不正、輝いていたスタッフの回答があるのに `shine` が空）があると止まる。

## KOS APIの取得方法

- ベースURL: `https://open-api.kos-solution.com`（`.dev` は開発用で、このキーでは使えない）
- 認証:
  1. `POST /open/authorization/commands/exchange-token` に `{"key": EHR_API_KEY}` を送り、`token` を受け取る
  2. 以後のリクエストは `Authorization: <token>` ヘッダーを付ける（期限切れなら401が返るので取り直す）
- 回答取得: `POST /schedule/open/v1/queries/find-satisfaction-survey-answers`
  - `submittedDateTimeRange`（提出日時、UTC、終点は含まない）で期間を指定する。1回の範囲は最大3か月まで
  - `limit` は最大1000だが、1か月分を1000件で取ると500エラーになったことがある → **月ごと・limit 200** で取る
  - `nextCursor` がある間はページを続けて取る
- 1回答に含まれるもの: テンプレート名、提出日時、予約日時、患者情報（`chartNumber`、`dateOfBirth`、`nationality`、`isNew` など）、
  設問ごとの回答（`surveyQuestionAnswers`）。設問には評価対象（`evaluationTarget`）が付く
  - `coordinator` = 受付（担当者名なし）／`counselor` = カウンセラー／`consultationDoctor` = 医師の診察／
    `procedureTaskDoctor` = 施術の担当者（医師も看護師も入る）／`hospital` = クリニック全体
- スタッフ一覧を取るAPIは無い。職種は `data/staff_roles.csv` で補う。

## 集計ルール（既存ダッシュボードと一致することを確認済み）

- 期間は **提出日（JST）** で区切る。8月は 8/11 以降（8/6〜10 の2件は元データ未収録のため含めない）。
- 職種スコアの設問:
  - 受付 =「受付の雰囲気を教えてください」
  - カウンセラー =「カウンセリングの質はいかがでしたか」
  - 医師 =「医師の診察の質を教えてください」＋ 担当者が医師の「施術の満足度を教えてください」
  - 看護師 = 担当者が医師以外の「施術の満足度を教えてください」
  - クリニック総評 =「NaAクリニックの総評をお願いします」
  - 医師かどうかは `staff_roles.csv` の「ダッシュボード職種＝医師」で判定する（南星炫さんは医師として扱う）
- 職種スコアの件数は評価の数（1回の来院で同じ職種が2名なら2件）。
- ドライバー（総評への効き方）: 回答者ごとにその職種の評価の平均を出し、★5群と★4以下群のクリニック総評平均の差、およびピアソン相関（小数3桁）。
- 担当者別: 評価はすべて数える。「担当回の総評」は同じ来院を1人1回だけ数える。
- 時間帯・曜日・属性: 回答者単位（その職種の評価の平均）。時間帯と曜日は **予約開始時刻（JST）**。
- 年代 = 提出年 − 生年（誕生日は考慮しない）を10歳刻み。属性は件数が minN（月タブ5・全期間10）未満の区分を省く。
- 要注意ライン: n ≥ minN かつ「職種平均より0.25pt以上低い」または「★3以下が15%以上」。
- 総評★3以下の回（lowClinic）: 総評★3以下の回答を、★の低い順 → 提出日の古い順 → 同じ日は提出時刻の遅い順に並べる。各職種の点（同じ職種が複数なら平均）と、その回のコメントをすべて（「なし」も含めて）載せる。

## コメント分類のルール

`prepare_labels.py` の作業ファイルで、コメントごとに `t`（テーマ、1〜2個）と `p`（内容）を付ける。
「なし」「特になし」「없음」「无」など中身のない回答はコメントとして扱わない（自動で除外済み）。

**テーマ `t`**（当てはまるものを最大2つ、主なものを先に）

| キー | 表示名 | 目安 |
|---|---|---|
| `manner` | 接遇・態度 | 笑顔、丁寧、優しい、感じがいい、雰囲気、真顔・無愛想 |
| `explain` | 説明のわかりやすさ | 説明が分かりやすい／足りない、的確、アフターケアの説明 |
| `listen` | 傾聴・相談対応 | 話を聞いてくれる、悩みに寄り添う、希望を汲む、質問しやすい |
| `skill` | 技術・仕上がり | 施術が丁寧・上手、仕上がり、効果、技術面の不安 |
| `pain` | 痛みへの配慮 | 痛くない、声かけ・様子見、麻酔、冷却 |
| `speed` | スピード・待ち時間 | スムーズ、早い、待たされた、診察が短い |
| `proposal` | 提案・営業姿勢 | 施術や回数券の提案、アップセルしない／強い、率直な助言 |
| `ops` | 連携・オペレーション | 引き継ぎ漏れ、予約・会計・ポイントの処理、スタッフ間の連携 |
| `env` | 清潔感・環境 | 院内がきれい、ドリンク、設備、音楽 |
| `other` | その他・判断保留 | どれにも当てはまらない、意味が取れない |

**内容 `p`**

| キー | 意味 | 目安 |
|---|---|---|
| `pos` | 肯定 | 良かった点だけ |
| `neg` | 改善要望 | 不満・要望が中心（★が高くても要望なら `neg`） |
| `mix` | 併記 | 良い点と要望が両方ある（例:「スムーズだったが、もう少しゆっくり診察してほしい」） |
| `neu` | 中立 | 事実だけ・評価が読み取れない |

ダッシュボードの「改善要望」の件数は `neg` ＋ `mix`。

**輝いていたスタッフ `shine`**（`[[名前, 職種], ...]`、1回答で複数可）

- 名前が分かる → `staff_roles.csv` の表記で `["大橋桃子", "カウンセラー"]`（苗字だけ・「さん」付きもフルネームに直す）
- 職種だけ分かる →`["受付（名前なし）", "受付"]`、`["看護師（名前なし）", "看護師"]` など
- 全員・特定できない →`["全員・特定なし", "-"]`
- 覚えていない・答えになっていない →`["無回答", "-"]`

## HTMLの作り方

ダッシュボードは1つのHTMLで、画面はすべて埋め込みJSON（`<script type="application/json" id="payload">`）から描画される。
`build.py` はこのJSONだけを書き換え、見た目（CSS・JavaScript）には触れない。

- `roles[職種].periods[aug|sep|oct|all]` … 職種タブの中身
  - 数値: `role` `clinic` `drivers` `staff` `hours` `dows` `segs`（API から再計算）
  - コメント: `comments`（`r` 職種, `t` テーマ, `p` 内容, `s` ★, `x` 本文, `tg` 担当者, `d` 提出日, `k` カルテ番号, `seg` `age` `nat`）、
    `roleThemes` `rolePol`（comments から集計）
  - `shine`（輝いていたスタッフの件数）、`lowClinic`（総評★3以下の回）、`meta`（件数・期間）、`copy`（見出し・説明文）
  - 医師タブの `kr1`（カウンセリング監査データ）は別データなので触らない
- `summary[期間]` … 横断サマリー（`copytext.summary` で生成）、`summary.trend` / `trendClinic` … 月別推移
- 説明文（`copy`）は `copytext.copy` のテンプレートで生成する。テンプレートは既存の文章を8〜10月分すべて一字一句再現する。
- フッターの「◯月分（…提出）はKOS OpenAPIから直接取得…（…更新）」の一文も `build.py` が更新する。
- 公開: Artifact の publish で `url` に上記URLを指定し、`build.py` の出力HTMLを渡す（`html_payload.read_html` が claude.ai の外枠を外す）。

## 未対応・決めること

- **クリニックスタッフ（共用アカウント）の除外**: 決定済みだが、8・9月との整合のため未反映。反映するなら全期間をそろえて集計し直す。
- **名前の表記ゆれ**: APIの担当者名（例:「山口真由」「山口彩茄」「吉澤沙也加」）と `staff_roles.csv`（KOS管理画面の表示「真由山口」など）が一致しない人がいる。医師の判定には影響しないが、職種を厳密に引くなら別名の対応が必要。
