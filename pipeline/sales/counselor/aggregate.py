"""API の生データ → カウンセラー販売実績ダッシュボードの `const D = {...}` を組み立てる。

定義はダッシュボードの「指標の定義」とフッターに書かれているとおりで、2026-10-11 に
3〜10月の公開値と1項目ずつ突き合わせて決めた（verify.py、README の照合表）。

- 販売（購入項目統計 = 購入エクスポート）: 1行 = 1購入明細。日付は購入日時（JST）。
  - 担当 = 担当カウンセラー（counselorNames）の先頭の名前。空なら会計担当者（assignees）の先頭の名前。
    ページの注記は「先頭の個人名」だが、公開値は共用アカウント（NaAクリニック等）が先頭でもそのまま
    共用アカウントに付けた場合と一致する（6〜8月で確認）。共用アカウントの会計はカウンセラー別に出ず、
    「クリニック全体」にだけ入る。
    表記ゆれ（例: "sayaka kudo"）は MAIN の表記に大文字小文字を無視して寄せる。
  - customers = 患者（visitorId）のユニーク数（月ごと）。ALL / VOCWIN は月の値の合計（延べ）、
    unique_customers は期間内の実人数。VOCWIN（VOC 全期間を選んだときの「同期間の販売実績」）は
    公開版に合わせて「VOC の月のうち最後の月を除いた月」の合計（2026-10-10 時点では 8〜9月）。
  - revenue = 会計金額（cost.totalAmount、割引・返金反映後）の合計。
  - procs = tx = 明細数。バンドル（procedureConfigurations が複数）は施術数に展開。
  - prepaid = 購入項目タイプ PREPAID_CARD_PRODUCT（項目分類「プリペイドカード」）。
  - course = 商品カテゴリ名に「コース」または「パッケージ」を含む明細。
  - refund = 購入状態 REFUNDED / PARTIALLY_REFUNDED の明細がある患者。
  - new = 患者登録日（JST）がその月の患者。
  - disc = 会計金額 ÷ 割引基準価格（basePriceAmountV2）。
  - one_rate = その月の施術数が1件だけの患者の割合。
  - チャネル = 患者流入チャネル（visitorFunnelName、初回流入）。
- 来院（予約統計 = 予約来院エクスポート）: 日付は予約開始日時（JST）。
  - 担当 = counselorNames のうち共用アカウントを除いた先頭の名前（6〜8月で完全一致）。
    2026-05-28 以前は予約にカウンセラーが入っていないことが多いので、空欄なら同じ日の会計の担当で補う。
  - visits = 受付済み（receptionDateTimeUtc あり）の予約行数（担当者別・クリニック全体とも）。
  - 進行時間 = consultationDwellTimeMinute が入っていて、カウンセラー欄が空でない行（共用アカウントでも可。
    クリニック全体の値に入る）。初診 = isFirstProcedureSchedule。
- VOC（満足度調査）: 提出日（JST）で月を分ける。2026-08-10 以降。
  - カウンセラー別 =「カウンセリングの質はいかがでしたか」の評価対象（担当カウンセラー）ごと。
  - チャネル = 回答者のカルテ番号 → 購入データの患者流入チャネル。
  - コメント = カウンセラー宛ての自由記述（評価対象ごと。「なし」も含めてそのまま。分類ラベルは無い）。
    ★ はその回答のカウンセリング評価の平均。
"""
import collections
import csv
import datetime as dt
import os
import statistics

JST = dt.timezone(dt.timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
STAFF_CSV = os.path.join(HERE, '..', '..', '..', 'data', 'staff_roles.csv')

OPEN_DAY = dt.date(2026, 3, 20)          # 開院日（全期間の始まり）
VOC_START = dt.date(2026, 8, 10)         # 満足度調査の開始日
COUNSELOR_ON_SCHEDULE_FROM = dt.date(2026, 5, 29)  # 予約データにカウンセラー名が入り始めた日
# 表示するカウンセラー（この順に色が付く）。新しいカウンセラーはここに足す（README「人の追加」）。
MAIN = ['大坪博史', '笹山みなみ', 'Sayaka Kudo', '永戸里菜', '大橋桃子', '仲田真歩', '小松遥']
CH_ORDER = ['ALL', 'LINE', 'GU', 'REF', 'HP', 'PAGE', 'OTHER']
CH_LABEL = {'ALL': '全チャネル', 'LINE': 'LINEリッチメニュー', 'GU': 'カンナムオンニ', 'REF': '紹介(referral)',
            'HP': 'ホームページ', 'PAGE': 'ページモード', 'OTHER': 'その他・不明'}
FUNNEL = {'LINEリッチメニュー': 'LINE', 'カンナムオンニ': 'GU', 'referral': 'REF', 'ホームページ': 'HP', 'ページモード': 'PAGE'}
DBANDS = [('〜10', 10), ('11-20', 20), ('21-30', 30), ('31-45', 45), ('46-60', 60), ('61〜', None)]
VOC_Q = {'カウンセリングの質はいかがでしたか': 'カウンセラー', '医師の診察の質を教えてください': '診察医師',
         '施術の満足度を教えてください': '施術者', '受付の雰囲気を教えてください': '受付',
         'NaAクリニックの総評をお願いします': 'クリニック'}
COMMENT_PREFIX = 'カウンセラーが'
REFUND = {'REFUNDED', 'PARTIALLY_REFUNDED'}

_STAFF = list(csv.DictReader(open(STAFF_CSV, encoding='utf-8')))
SHARED = {r['氏名'] for r in _STAFF if '集計から除外' in r['備考']}   # クリニックスタッフ, NaAクリニック


def jdt(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(JST)


def ym(d):
    return d.strftime('%Y-%m')


def val(o):
    return (o or {}).get('value') or 0


_LOWER = {n.lower(): n for n in MAIN}


def norm(name):
    return _LOWER.get((name or '').strip().lower(), (name or '').strip())


def first_personal(names):
    for n in names or []:
        if n and n not in SHARED:
            return norm(n)
    return None


def first_listed(names):
    """会計の担当: 並んでいる先頭の名前（共用アカウントでもそのまま。公開版はこの扱いで一致する）。"""
    for n in names or []:
        if n:
            return norm(n)
    return None


def channel(funnel_name):
    return FUNNEL.get(funnel_name or '', 'OTHER')


# ---------------------------------------------------------------- 行の整形

def purchase_rows(raw, gaps=()):
    """購入項目統計 → 集計用の行。gaps は (開始, 終了) の JST datetime の組（エクスポートの欠損を再現するとき）。"""
    out = []
    for r in raw:
        t = jdt(r['createdDateTimeUtc'])
        if any(a <= t < b for a, b in gaps):
            continue
        out.append(dict(
            ts=t, pid=r['visitorId'], chart=r.get('visitorChartNumber') or '', date=t.date(), m=ym(t),
            who=first_listed(r.get('counselorNames')) or first_listed([a.get('name') for a in r.get('assignees') or []]),
            ch=channel(r.get('visitorFunnelName')),
            amt=val((r.get('cost') or {}).get('totalAmount')), base=val(r.get('basePriceAmountV2')),
            procs=max(1, len(r.get('procedureConfigurations') or [])),
            prepaid=r.get('purchaseItemType') == 'PREPAID_CARD_PRODUCT',
            course=any(('コース' in c or 'パッケージ' in c) for c in r.get('productCategoryNames') or []),
            refund=r.get('purchaseStatus') in REFUND,
            new_m=ym(jdt(r['visitorCreatedDateTimeUtc'])) if r.get('visitorCreatedDateTimeUtc') else None))
    return out


def schedule_rows(raw, skip_days=(), fallback=None):
    """予約統計 → 集計用の行。fallback は {(visitorId, 日付): 会計の担当}。
    KOS で予約にカウンセラーが入るようになったのは 2026-05-29 から（それ以前は5〜8割が空欄）。
    それより前の空欄の行だけ、同じ日の会計の担当で補う（公開版のエクスポートに近づく。README の照合表）。"""
    out = []
    for x in raw:
        t = jdt(x['reservationStartDateTimeUtc'])
        if t.date() in skip_days:
            continue
        who = first_personal(x.get('counselorNames'))
        # クリニック全体の進行時間は「カウンセラー欄がある行」。5/28 以前は欄が API に残っていないので全行
        listed = bool(x.get('counselorNames')) or t.date() < COUNSELOR_ON_SCHEDULE_FROM
        if who is None and not x.get('counselorNames') and fallback and t.date() < COUNSELOR_ON_SCHEDULE_FROM:
            who = fallback.get((x.get('visitorId'), t.date()))
        out.append(dict(date=t.date(), m=ym(t), who=who, listed=listed,
                        received=bool(x.get('receptionDateTimeUtc')),
                        dwell=x.get('consultationDwellTimeMinute'), first=bool(x.get('isFirstProcedureSchedule'))))
    return out


def purchase_attribution(rows):
    """{(visitorId, 日付): その日の最初の会計の担当}（schedule_rows の fallback 用）。"""
    out = {}
    for r in sorted(rows, key=lambda r: r['ts']):
        out.setdefault((r['pid'], r['date']), r['who'])
    return out


def survey_rows(raw, chart_channel, until=None, skip=()):
    """満足度調査 → 回答ごとの {date, m, ch, ratings{区分: [(対象者, 点)]}, counselor_comment}。"""
    out = []
    for a in raw:
        t = jdt(a['submittedDateTimeUtc'])
        if t.date() < VOC_START or (until and t.date() > until) or any(s <= t < e for s, e in skip):
            continue
        ch = chart_channel.get((a.get('submittedVisitor') or {}).get('chartNumber') or '', 'OTHER')
        rat, com = collections.defaultdict(list), []
        for q in a['surveyQuestionAnswers']:
            title = q['title'].strip()
            ans = q.get('submittedAnswer') or {}
            target = (next(iter((q.get('evaluationTarget') or {}).values()), {}) or {}).get('name', '')
            if title in VOC_Q and (ans.get('number') or {}).get('value') is not None:
                rat[VOC_Q[title]].append((norm(target), float(ans['number']['value'])))
            elif title.startswith(COMMENT_PREFIX) and (ans.get('text') or {}).get('value') is not None:
                com.append((norm(target), ans['text']['value'].strip()))
        out.append(dict(date=t.date(), m=ym(t), ch=ch, rat=rat, comments=com, ts=t))
    return out


# ---------------------------------------------------------------- 販売ブロック

def _finish(b):
    c = b['customers']
    d = lambda x, y: x / y if y else 0.0  # noqa: E731
    b['arpu'] = d(b['revenue'], c)
    b['prepaid_rate'] = d(b['prepaid_cust'], c)
    b['course_rate'] = d(b['course_cust'], c)
    b['refund_rate'] = d(b['refund_cust'], c)
    b['new_rate'] = d(b['new_cust'], c)
    b['procs_per_cust'] = d(b['procs'], c)
    b['price_per_proc'] = d(b['revenue'], b['procs'])
    b['disc'] = d(b['revenue'], b.pop('_base'))
    b['one_rate'] = d(b.pop('_one'), c)
    return b


def sales_block(rows, m, visits=0):
    """1か月・1担当（またはクリニック全体）・1チャネルの行 → ブロック。"""
    cust = {r['pid'] for r in rows}
    per = collections.Counter()
    for r in rows:
        per[r['pid']] += r['procs']
    pre = [r for r in rows if r['prepaid']]
    cou = [r for r in rows if r['course']]
    b = dict(customers=len(cust), tx=sum(per.values()), revenue=float(sum(r['amt'] for r in rows)),
             prepaid_cust=len({r['pid'] for r in pre}), prepaid_amt=float(sum(r['amt'] for r in pre)),
             course_cust=len({r['pid'] for r in cou}), course_amt=float(sum(r['amt'] for r in cou)),
             refund_cust=len({r['pid'] for r in rows if r['refund']}),
             new_cust=len({r['pid'] for r in rows if r['new_m'] == m}),
             procs=sum(per.values()), visits=visits,
             _base=sum(r['base'] for r in rows), _one=sum(1 for v in per.values() if v == 1))
    return _finish(b)


SUM_KEYS = ['customers', 'tx', 'revenue', 'prepaid_cust', 'prepaid_amt', 'course_cust', 'course_amt',
            'refund_cust', 'new_cust', 'procs', 'visits']


def sum_block(blocks, rows):
    """月ブロックの合計（延べ）。値引後率と1施術のみ率は月の分子・分母を足して出す。"""
    b = {k: sum(x[k] for x in blocks) for k in SUM_KEYS}
    b['revenue'] = float(b['revenue'])
    b['_base'] = sum(r['base'] for r in rows)
    b['_one'] = sum(x['one_rate'] * x['customers'] for x in blocks)
    b = _finish(b)
    b['one_rate'] = round(b['one_rate'] * b['customers']) / b['customers'] if b['customers'] else 0.0
    return b


# ---------------------------------------------------------------- 進行時間

def duration_block(vals, firsts=None, arpu=None):
    if not vals:
        return None
    o = dict(n=len(vals), med=float(statistics.median(vals)), mean=statistics.mean(vals), hours=sum(vals) / 60)
    if firsts is not None:
        f = [v for v, fl in zip(vals, firsts) if fl]
        r = [v for v, fl in zip(vals, firsts) if not fl]
        o.update(first=float(statistics.median(f)) if f else None, first_n=len(f),
                 repeat=float(statistics.median(r)) if r else None, repeat_n=len(r))
    o['per_min'] = arpu / o['med'] if arpu and o['med'] else None
    if firsts is not None:
        dist = collections.Counter()
        for v in vals:
            dist[next(k for k, hi in DBANDS if hi is None or v <= hi)] += 1
        o['dist'] = {k: dist.get(k, 0) for k, _ in DBANDS}
    return o


# ---------------------------------------------------------------- VOC

def score_block(xs, dist=False):
    if not xs:
        return dict(mean=0, n=0, low=0, top=0) if not dist else None
    o = dict(mean=sum(xs) / len(xs), n=len(xs), low=sum(1 for x in xs if x <= 3), top=sum(1 for x in xs if x >= 5) / len(xs))
    if dist:
        c = collections.Counter(int(x) for x in xs)
        o['dist'] = {str(k): c[k] for k in (5, 4, 3, 2, 1) if c[k]}
    return o


def voc_block(answers, main, exclude_shared=False):
    clinic, byc = collections.defaultdict(list), collections.defaultdict(list)
    for a in answers:
        for kind, lst in a['rat'].items():
            for who, s in lst:
                if exclude_shared and who in SHARED:
                    continue
                clinic[kind].append(s)
                if kind == 'カウンセラー' and who in main:
                    byc[who].append(s)
    return dict(clinic={k: score_block(clinic[k]) for k in VOC_Q.values()},
                by_counselor={n: score_block(v, dist=True) for n, v in sorted(byc.items())})


def comments(answers):
    """カウンセラーごとのコメント一覧（新しい順）。本文はそのカウンセラー宛ての自由記述、
    s はその回答のカウンセリング評価の平均（1回の来院で複数名を評価した場合は全員の平均。公開版と同じ）。"""
    out = collections.defaultdict(list)
    for a in sorted(answers, key=lambda a: a['ts'], reverse=True):
        cs = [x for _, x in a['rat'].get('カウンセラー') or []]
        s = sum(cs) / len(cs) if cs else None
        for who, text in a['comments']:
            if who:
                out[who].append(dict(t=text, s=s, d=a['date'].isoformat(), c=a['ch']))
    return dict(out)


# ---------------------------------------------------------------- 全体

def build(purchases, schedules, answers, last_date, voc_last=None, visit_last=None, main=MAIN, exclude_shared_voc=False):
    """整形済みの行 → D。months は開院月から last_date の月まで。"""
    months, m = [], OPEN_DAY.replace(day=1)
    while m <= last_date:
        months.append(ym(m))
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    purchases = [r for r in purchases if OPEN_DAY <= r['date'] <= last_date]
    schedules = [x for x in schedules if OPEN_DAY <= x['date'] <= (visit_last or last_date)]
    voc_months = [mm for mm in months if mm >= ym(VOC_START)]
    vocwin = voc_months[:-1] if len(voc_months) > 1 else voc_months   # 公開版の VOCWIN は「締めた VOC 月」の合計

    by = collections.defaultdict(list)            # (who|None, ch, m) -> rows ; who None = クリニック全体
    for r in purchases:
        for w in {None, r['who']}:
            for ch in {'ALL', r['ch']}:
                by[(w, ch, r['m'])].append(r)
    vis_c = collections.Counter(x['m'] for x in schedules if x['received'])
    vis_w = collections.Counter((x['who'], x['m']) for x in schedules if x['who'] and x['received'])

    def series(w, ch):
        out, mblocks, rows_all = {}, {}, []
        for mm in months:
            rows = by.get((w, ch, mm), [])
            visits = 0 if ch != 'ALL' else (vis_c[mm] if w is None else vis_w[(w, mm)])
            if w is not None and not rows and not visits:
                continue
            out[mm] = mblocks[mm] = sales_block(rows, mm, visits)
            rows_all += rows
        if w is not None and not mblocks:
            return out
        b = sum_block(list(mblocks.values()), rows_all)
        b['unique_customers'] = len({r['pid'] for r in rows_all})
        out['ALL'] = b
        wins = [mblocks[mm] for mm in vocwin if mm in mblocks]
        if wins:
            out['VOCWIN'] = sum_block(wins, [r for mm in vocwin for r in by.get((w, ch, mm), [])])
        return out

    clinic = {ch: series(None, ch) for ch in CH_ORDER}
    counselors = {}
    for n in main:
        counselors[n] = {ch: series(n, ch) for ch in CH_ORDER}
        allb = counselors[n]['ALL'].get('ALL')
        if allb:
            allb['since'] = min(r['date'] for r in purchases if r['who'] == n).isoformat()

    # 進行時間
    dw = collections.defaultdict(list)
    for x in schedules:
        if x['dwell'] is not None and x['listed']:
            for k in {(x['who'], x['m']), (x['who'], 'ALL'), (None, x['m']), (None, 'ALL')}:
                dw[k].append((x['dwell'], x['first']))
    duration = {}
    for n in main:
        duration[n] = {}
        for mm in months + ['ALL']:
            v = dw.get((n, mm))
            if v:
                arpu = (counselors[n]['ALL'].get(mm) or {}).get('arpu')
                duration[n][mm] = duration_block([a for a, _ in v], [f for _, f in v], arpu)
    duration_clinic = {}
    for mm in months + ['ALL']:
        v = dw.get((None, mm))
        if v:
            duration_clinic[mm] = duration_block([a for a, _ in v], None, clinic['ALL'][mm]['arpu'])

    # VOC
    voc = {}
    for ch in CH_ORDER:
        sel = [a for a in answers if ch == 'ALL' or a['ch'] == ch]
        voc[ch] = {mm: voc_block([a for a in sel if a['m'] == mm], main, exclude_shared_voc) for mm in voc_months}
        voc[ch]['ALL'] = voc_block(sel, main, exclude_shared_voc)
    com = {mm: comments([a for a in answers if a['m'] == mm]) for mm in voc_months}
    com['ALL'] = comments(answers)
    com = {p: {n: v for n, v in sorted(d.items()) if n in main} for p, d in com.items()}

    days = collections.defaultdict(set)
    for r in purchases:
        days[r['m']].add(r['date'])
    month_range = {}
    for mm in months:
        y, mo = int(mm[:4]), int(mm[5:])
        start = max(dt.date(y, mo, 1), OPEN_DAY)
        end = min((dt.date(y, mo, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1), last_date)
        month_range[mm] = [start.isoformat(), end.isoformat(), len(days[mm])]

    return dict(months=months, main=list(main), ch_order=CH_ORDER, ch_label=CH_LABEL, clinic=clinic,
                counselors=counselors, voc=voc, comments=com, voc_months=voc_months, duration=duration,
                duration_clinic=duration_clinic, month_range=month_range, excluded_dates=[],
                last_date=last_date.isoformat(), voc_last=(voc_last or last_date).isoformat(),
                visit_last=(visit_last or last_date).isoformat())
