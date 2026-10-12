"""API の生データ → 看護師ダッシュボードの `const EMBED = {T, P, S, files}` を組み立てる。

EMBED は集計値ではなく、ページの Excel 読み込み（施術・購入・満足度調査の3ファイル）と同じ形の「行」で、
集計はページの JS（compute / build）がする。だからここでは Excel エクスポートの行を API から作り直すだけ。
2026-10-12 に公開版（10/1〜10/10 のエクスポート）と行単位で突き合わせて決めた（README の照合表）。

T（施術 ≒ 施術タスク統計 get-procedure-task-statistics）
    グループ行 ' -> 施術者 -> YYYY.MM.DD -> 患者 -> 施術名 -> 担当カウンセラー' の下に
    明細行 [None, 商品カテゴリ, 商品名, 担当者, 担当カウンセラー]。
    - 施術者 = doctorNames を ',' でつなぐ（空なら「データなし」）。日付 = 完了日時（JST）。
    - 施術名 = procedureName（無ければ ''）、商品名 = productTitle（ドクター診察など商品のない行は None
      → ページで除外）、商品カテゴリ = productCategoryNames を ','、担当者 = assigneeNames を ','、
      担当カウンセラー = counselorNames を ','（明細では空なら None、グループでは「データなし」）。
    - Excel 版は「施術名 → 施術者 → …」の並びのファイルもあった（ページはどちらも読める）。ここでは
      施術者を先頭にする並びで出す。
P（購入 ≒ 購入項目統計 get-purchase-item-statistics、グループ行を除いた明細）
    [発生日時 'YYYY.MM.DD HH:MM:SS', 患者, 施術外品目名, 施術外品目カテゴリ名, 患者分類, 会計状態]
    - 施術外品目 = etceteraProductName / etceteraProductCategoryName（ETCETRA_PRODUCT の行だけ。指名料は
      カテゴリ「指名料」、品目「看護師_○○」）。患者分類 = visitorCategoryNames を ','（取得時点の分類）。
    - 会計状態: ACCEPTED 承認済み / REFUNDED 返金済み / PARTIALLY_REFUNDED 一部返金済み。
S（満足度調査 ≒ 満足度調査アンケート結果「設問回答」シート。提出日で期間を切る）
    [予約日時 'YYYY-MM-DD HH:MM:SS', 患者, 評価対象タイプ, 評価対象, 設問タイプ, 設問タイトル, 集計用スコア, 回答値, 回答ID]
    - 評価対象タイプ: coordinator 受付 / counselor カウンセラー / consultationDoctor 診察医師 /
      procedureTaskDoctor 施術者 / hospital クリニック。評価対象 = その name（受付・クリニックは None）。
    - 数値入力式: スコア = 数値、回答値 = 数値の文字列。記述式: スコア None、回答値 = 文字列（未回答は None）。

患者 = 'P' + md5(visitorId) の先頭8桁（Excel 版は患者名のハッシュ。ページでは同じ日の施術と購入を結ぶ
キーにしか使わないので、名前を取らずに visitorId から作る）。
"""
import datetime as dt
import hashlib

JST = dt.timezone(dt.timedelta(hours=9))
S_TYPE = {'coordinator': '受付', 'counselor': 'カウンセラー', 'consultationDoctor': '診察医師',
          'procedureTaskDoctor': '施術者', 'hospital': 'クリニック'}
STATUS = {'ACCEPTED': '承認済み', 'REFUNDED': '返金済み', 'PARTIALLY_REFUNDED': '一部返金済み'}


def jdt(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(JST)


def pt(visitor_id):
    return 'P' + hashlib.md5((visitor_id or '').encode()).hexdigest()[:8]


def join(xs):
    xs = [x for x in xs or [] if x]
    return ','.join(xs) or None


def in_range(t, d0, d1):
    return d0 <= t.date() <= d1


def t_rows(raw, d0, d1):
    """施術タスク → T（グループ行＋明細行）。"""
    recs = []
    for r in raw:
        t = jdt(r['completedDateTimeUtc'])
        if not in_range(t, d0, d1):
            continue
        perf = join(r.get('doctorNames')) or 'データなし'
        recs.append((perf, t.strftime('%Y.%m.%d'), pt(r.get('visitorId')), r.get('procedureName') or '',
                     join(r.get('counselorNames')) or 'データなし', t,
                     [None, join(r.get('productCategoryNames')), r.get('productTitle') or None,
                      join(r.get('assigneeNames')), join(r.get('counselorNames'))]))
    recs.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4], x[5]))
    out, last = [], ()
    for perf, day, p, proc, couns, _, leaf in recs:
        path = (perf, day, p + ' ', proc, couns)
        for i in range(5):
            if last[:i + 1] != path[:i + 1]:
                out.append([' -> ' + ' -> '.join(path[:i + 1]), None, None, None, None])
        last = path
        out.append(leaf)
    return out


def p_rows(raw, d0, d1):
    out = []
    for r in sorted(raw, key=lambda r: r['createdDateTimeUtc']):
        t = jdt(r['createdDateTimeUtc'])
        if not in_range(t, d0, d1):
            continue
        etc = r.get('purchaseItemType') == 'ETCETRA_PRODUCT'
        out.append([t.strftime('%Y.%m.%d %H:%M:%S'), pt(r.get('visitorId')),
                    (r.get('etceteraProductName') or None) if etc else None,
                    (r.get('etceteraProductCategoryName') or None) if etc else None,
                    join(r.get('visitorCategoryNames')),
                    STATUS.get(r.get('purchaseStatus'), r.get('purchaseStatus'))])
    return out


def _num(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def s_rows(raw, d0, d1):
    out = []
    for a in sorted(raw, key=lambda a: a['submittedDateTimeUtc'], reverse=True):
        if not in_range(jdt(a['submittedDateTimeUtc']), d0, d1):
            continue
        res = jdt(a['reservationDateTimeUtc']['startDateTimeUtc']).strftime('%Y-%m-%d %H:%M:%S')
        p = pt((a.get('submittedVisitor') or {}).get('visitorId'))
        for q in sorted(a['surveyQuestionAnswers'], key=lambda q: q.get('order', 0)):
            et = q.get('evaluationTarget') or {}
            kind = next(iter(et), None)
            target = (et.get(kind) or {}).get('name') if kind else None
            ans = q.get('submittedAnswer') or {}
            if 'number' in q:
                v = (ans.get('number') or {}).get('value')
                score, val, qt = (float(v), _num(v), '数値入力式') if v is not None else (None, None, '数値入力式')
            else:
                score, val, qt = None, (ans.get('text') or {}).get('value'), '記述式'
                if val == 'None':      # Excel エクスポートでは空欄になる（「なし」の意味の回答）
                    val = None
            out.append([res, p, S_TYPE.get(kind, kind), target or None, qt, q['title'], score, val, a['id']])
    return out


def build(procedure, purchase, survey, d0, d1, note=None):
    """d0..d1（JST、両端含む）の EMBED。files はページでは使われない（出典のメモ）。"""
    return {'T': t_rows(procedure, d0, d1), 'P': p_rows(purchase, d0, d1), 'S': s_rows(survey, d0, d1),
            'files': [note or f'KOS OpenAPI {d0.isoformat()}〜{d1.isoformat()}（施術タスク・購入項目・満足度調査）']}
