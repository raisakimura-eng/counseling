"""Turn raw KOS survey answers into the numeric blocks of the dashboard payload.

Every rule here was checked against the hand-built Aug/Sep data: running it on
the API data for those months reproduces the published numbers exactly
(see verify.py).
"""
import collections
import csv
import datetime as dt
import json
import os

JST = dt.timezone(dt.timedelta(hours=9))
ROLES = ['受付', 'カウンセラー', '医師', '看護師']
# Rating questions -> role. 施術 is split by the evaluated staff member: doctors -> 医師, everyone else -> 看護師.
RATING_Q = {'受付の雰囲気を教えてください': '受付', 'カウンセリングの質はいかがでしたか': 'カウンセラー',
            '医師の診察の質を教えてください': '医師', '施術の満足度を教えてください': '施術',
            'NaAクリニックの総評をお願いします': 'clinic'}
# Free-text questions, matched by title prefix
COMMENT_Q = {'受付が': '受付', 'カウンセ': 'カウンセラー', '医師の診': '医師', '施術の「': '施術'}
SHINE_Q = '輝いて'
NAT = {'JP': '日本', 'KR': '韓国', 'CN': '中国', 'TW': '台湾', 'US': 'アメリカ', 'VN': 'ベトナム', 'TH': 'タイ', 'HK': '香港'}
DOW = '月火水木金土日'
# Answers that mean "nothing to say"; they are not listed as comments
EMPTY = {'なし', '特になし', '特に無し', '無し', '없음', '无', 'none', 'ない', '特にない', '-', 'ナシ', 'n/a', 'na', 'x', ''}

STAFF_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'staff_roles.csv')
_STAFF = list(csv.DictReader(open(STAFF_CSV, encoding='utf-8')))
STAFF_ROLE = {r['氏名']: r['ダッシュボード職種'] for r in _STAFF}
# Accounts marked 「集計から除外」 in staff_roles.csv (shared logins such as クリニックスタッフ): their ratings and
# comments are dropped everywhere, so they never count towards a role, the staff list or 総評★3以下の回.
EXCLUDED = {r['氏名'] for r in _STAFF if '集計から除外' in r['備考']}
DOCTORS = {name for name, role in STAFF_ROLE.items() if role == '医師'}


def jdt(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(JST)


def mean(x):
    return sum(x) / len(x) if x else None


def is_empty(text):
    return text.strip().strip('。.!！ ').lower() in EMPTY


def _target(q):
    return (next(iter((q.get('evaluationTarget') or {}).values()), {}) or {}).get('name', '')


def _role(kind, target):
    return kind if kind != '施術' else ('医師' if target in DOCTORS else '看護師')


def parse(a):
    """One API response -> numeric record."""
    sub = jdt(a['submittedDateTimeUtc'])
    res = jdt(a['reservationDateTimeUtc']['startDateTimeUtc'])
    v = a['submittedVisitor']
    rat, clinic = [], None
    for q in a['surveyQuestionAnswers']:
        kind = RATING_Q.get(q['title'].strip())
        val = (q.get('submittedAnswer') or {}).get('number', {}).get('value')
        if not kind or val is None:
            continue
        if kind == 'clinic':
            clinic = int(val)
            continue
        name = _target(q)
        if name in EXCLUDED:
            continue
        rat.append((_role(kind, name), name, int(val)))
    # age = submitted year - birth year (this is how the original dashboard bucketed ages)
    age = f"{(sub.year - int(v['dateOfBirth'][:4])) // 10 * 10}代" if v.get('dateOfBirth') else None
    return dict(id=a['id'], date=sub.strftime('%Y-%m-%d'), sub=sub, res=res, clinic=clinic, rat=rat,
                seg='新規' if v.get('isNew') else '既存', age=age,
                nat=NAT.get(v.get('nationality') or '', v.get('nationality') or ''), chart=v.get('chartNumber') or '')


def extract_comments(a):
    """Free-text answers of one response: ([{r, tg, s, x, empty}], shine_text)."""
    qs = a['surveyQuestionAnswers']
    out, shine = [], None
    for q in qs:
        if 'text' not in q or not q.get('submittedAnswer'):
            continue
        text = q['submittedAnswer'].get('text', {}).get('value', '').strip()
        if SHINE_Q in q['title']:
            shine = text
            continue
        kind = next((v for k, v in COMMENT_Q.items() if q['title'].startswith(k)), None)
        if not kind:
            continue
        tg = _target(q)
        if tg in EXCLUDED:
            continue
        role = _role(kind, tg)
        score = None  # star rating given to the same evaluation target
        for q2 in qs:
            if 'number' in q2 and q2.get('submittedAnswer') and q2.get('evaluationTarget') == q.get('evaluationTarget'):
                score = int(q2['submittedAnswer']['number']['value'])
        out.append(dict(r=role, tg='' if role == '受付' else tg, s=score, x=text, empty=is_empty(text)))
    return out, shine


def load(*files):
    """Raw JSON files from kos_client.py -> (records, {id: raw}) with duplicates removed."""
    recs, raw = [], {}
    for f in files:
        for a in json.load(open(f))['data']:
            if a['id'] in raw:
                continue
            raw[a['id']] = a
            recs.append(parse(a))
    return recs, raw


def dist_stats(vals):
    d = [vals.count(i) for i in range(1, 6)]
    n = len(vals)
    return dict(n=n, avg=mean(vals), dist=d, top=(d[4] / n * 100) if n else 0, low=sum(d[:3]))


def pearson(x, y):
    if len(x) < 3:
        return None
    mx, my = mean(x), mean(y)
    sx = sum((a - mx) ** 2 for a in x) ** .5
    sy = sum((b - my) ** 2 for b in y) ** .5
    return round(sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy), 3) if sx and sy else None


def role_numeric(recs, role, min_n):
    """role / clinic / drivers / staff / hours / dows / segs for one role and period."""
    ratings = [(rec, n, v) for rec in recs for (r, n, v) in rec['rat'] if r == role]
    out = {'role': dist_stats([v for _, _, v in ratings]),
           'clinic': dist_stats([r['clinic'] for r in recs if r['clinic']])}
    # drivers: per respondent, the mean of that role's ratings vs. the clinic score
    drv = []
    for R in ROLES:
        xs, ys = [], []
        for rec in recs:
            vs = [v for (r, n, v) in rec['rat'] if r == R]
            if vs and rec['clinic']:
                xs.append(mean(vs))
                ys.append(rec['clinic'])
        hi = [y for x, y in zip(xs, ys) if x == 5]
        lo = [y for x, y in zip(xs, ys) if x < 5]
        drv.append(dict(role=R, n=len(xs), r=pearson(xs, ys), hi=mean(hi), nhi=len(hi), lo=mean(lo), nlo=len(lo)))
    out['drivers'] = drv
    # staff: every rating counts; the clinic average counts each visit once per person
    st, sc = collections.defaultdict(list), collections.defaultdict(dict)
    for rec, n, v in ratings:
        st[n].append(v)
        if rec['clinic']:
            sc[n][rec['id']] = rec['clinic']
    out['staff'] = [] if role == '受付' else sorted(
        [dict(name=k, n=len(x), avg=mean(x), low=sum(a <= 3 for a in x), cavg=mean(list(sc[k].values())), cn=len(sc[k]))
         for k, x in st.items()], key=lambda s: (-s['avg'], -s['n']))
    # hours / weekdays: per respondent (mean of that role), by reservation start (JST)
    resp = [(rec, mean([v for (r, n, v) in rec['rat'] if r == role])) for rec in recs if any(r == role for (r, n, v) in rec['rat'])]
    hrs, dw = collections.defaultdict(list), collections.defaultdict(list)
    for rec, v in resp:
        hrs[rec['res'].hour].append((v, rec['clinic']))
        dw[rec['res'].weekday()].append((v, rec['clinic']))
    out['hours'] = [dict(h=h, n=len(hrs[h]), avg=mean([a for a, _ in hrs[h]]), low=sum(a <= 3 for a, _ in hrs[h]),
                         cavg=mean([c for _, c in hrs[h] if c])) for h in range(10, 19) if hrs[h]]
    out['dows'] = [dict(d=DOW[i], n=len(dw[i]), avg=mean([a for a, _ in dw[i]]), cavg=mean([c for _, c in dw[i] if c]))
                   for i in range(7) if dw[i]]
    segs = {}
    for key in ('seg', 'age', 'nat'):
        g = collections.defaultdict(list)
        for rec, v in resp:
            if rec[key]:
                g[rec[key]].append((v, rec['clinic']))
        segs[key] = sorted([dict(v=k, n=len(x), recep=mean([a for a, _ in x]), clinic=mean([c for _, c in x if c]))
                            for k, x in g.items() if len(x) >= min_n], key=lambda s: -s['n'])
    out['segs'] = segs
    return out


def low_clinic(recs, raw):
    """Visits whose clinic score is ★3 or lower, with every role's score and every comment of that visit.

    Order: score ascending, then submitted date ascending, later submissions first within a day
    (this reproduces the hand-built Aug/Sep/Oct lists exactly).
    """
    out = []
    for rec in sorted((r for r in recs if r['clinic'] is not None and r['clinic'] <= 3),
                      key=lambda r: (r['clinic'], r['date'], -r['sub'].timestamp())):
        roles = {}
        for R in ROLES:
            vs = [v for (r, n, v) in rec['rat'] if r == R]
            if vs:
                roles[R] = float(mean(vs))
        cm, _ = extract_comments(raw[rec['id']])
        out.append(dict(chart=rec['chart'], date=rec['date'], score=rec['clinic'], seg=rec['seg'], age=rec['age'], nat=rec['nat'],
                        roles=roles, comments=[dict(role=c['r'], shine=False, target=c['tg'], text=c['x']) for c in cm]))
    return out
