"""Rebuild the current month and 全期間 of the 4職種横断ダッシュボード from KOS data.

Usage:
    python3 -I pipeline/build.py --html CURRENT_HTML --period oct --label 10月 \
        --month RAW_OCT.json --all RAW_AUG.json RAW_SEP.json RAW_OCT.json \
        --labels LABELS.json --sub-to 2026-10-11 --out NEW_HTML

- Numeric blocks (scores, drivers, staff, hours, weekdays, segments) are recomputed
  from the API data for the month and for all months.
- Comments, themes and 「輝いていたスタッフ」 are kept from the current HTML; the
  responses in LABELS (prepare_labels.py output with t/p/shine filled in) are added.
- Summary blocks, the month trend and all narrative copy are regenerated.
- 「総評★3以下の回」(lowClinic) is rebuilt from the API data.
- A month that is not on the dashboard yet gets a new tab (before 全期間).
- Earlier closed months are left untouched.
Both the raw files and the output HTML contain patient data: keep them outside the repository.
"""
import argparse
import copy as cp
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copytext  # noqa: E402
from aggregate import EXCLUDED, ROLES, STAFF_ROLE, extract_comments, load, low_clinic, role_numeric  # noqa: E402
from html_payload import get_payload, read_html, set_payload  # noqa: E402

POL_ORDER = {'neg': 0, 'mix': 1, 'neu': 2, 'pos': 3}
THEME_KEYS = {k for k, _ in copytext.THEMES}


def labelled_items(labels, raw, recs_by_id):
    """Validate LABELS against the API data and return (comments, shine mentions, n shine answers)."""
    comments, shine, n_shine = [], [], 0
    for item in labels:
        rec = recs_by_id[item['id']]
        cm, sh = extract_comments(raw[item['id']])
        cm = [c for c in cm if not c['empty']]
        assert [c['x'] for c in cm] == [c['x'] for c in item['comments']], f"comments changed: {item['date']} {item['time']}"
        for c, lab in zip(cm, item['comments']):
            assert lab['t'] and set(lab['t']) <= THEME_KEYS and lab['p'] in POL_ORDER, f"unlabelled comment: {item['date']} {item['time']}"
            comments.append(dict(r=c['r'], t=lab['t'], p=lab['p'], s=c['s'], x=c['x'], tg=c['tg'], d=rec['date'],
                                 k=rec['chart'], seg=rec['seg'], age=rec['age'], nat=rec['nat']))
        if sh and sh.strip():
            assert item['shine'], f"shine answer not classified: {item['date']} {item['time']}"
            n_shine += 1
            shine += [tuple(s) for s in item['shine']]
    return comments, shine, n_shine


def merge_shine(old, new):
    d = {s['name']: dict(s) for s in old}
    for name, role in new:
        d.setdefault(name, dict(name=name, role=role, n=0))['n'] += 1
        if d[name]['role'] == 'unknown' and STAFF_ROLE.get(name) in ROLES:
            d[name]['role'] = STAFF_ROLE[name]
    return sorted(d.values(), key=lambda s: -s['n'])


def add_month(p, per, label):
    """Add an empty tab for a new month, modelled on the latest month (inserted before 全期間)."""
    months = [x['key'] for x in p['periodList'] if x['key'] != 'all']
    prev = months[-1]
    for R in ROLES:
        E = cp.deepcopy(p['roles'][R]['periods'][prev])
        E.pop('kr1', None)  # counseling-audit data is month specific and not produced by this pipeline
        E.update(comments=[], shine=[], lowClinic=[])
        E['meta'].update(period=label, nShine=0, nRoleComment=0, nRoleReq=0, subFrom=None, subTo=None)
        p['roles'][R]['periods'][per] = E
    p['periodList'].insert(len(months), dict(key=per, label=label))
    for t in p['summary']['trend']:
        t['months'].append(dict(k=per, lab=label, avg=None, n=0, req=0, com=0))
    p['summary']['trendClinic'].append(dict(k=per, lab=label, avg=None, n=0, to=None))


def rebuild_period(p, per, label, recs, raw, comments, shine, n_shine, sub_to):
    P = {}
    low = low_clinic(recs, raw)
    for R in ROLES:
        E = p['roles'][R]['periods'][per]
        N = cp.deepcopy(E)
        N.update(role_numeric(recs, R, E['meta']['minN']))
        N['hoursSparse'] = max((h['n'] for h in N['hours']), default=0) < 8
        N['lowClinic'] = low
        N['comments'] = sorted([c for c in E['comments'] if c['tg'] not in EXCLUDED] + [c for c in comments if c['r'] == R],
                               key=lambda c: (POL_ORDER[c['p']], c['s'] or 9, c['d']))
        N['roleThemes'], N['rolePol'] = copytext.themes_pol(N['comments'])
        N['shine'] = merge_shine(E['shine'], shine)
        N['meta'].update(nResp=len(recs), nRoleComment=len(N['comments']), nRoleReq=N['rolePol']['neg'] + N['rolePol']['mix'],
                         nShine=E['meta']['nShine'] + n_shine, subTo=sub_to,
                         subFrom=E['meta']['subFrom'] or min(r['date'] for r in recs))
        P[R] = N
    for R in ROLES:
        P[R]['copy'] = copytext.copy(P, R, label)
        p['roles'][R]['periods'][per] = P[R]
    p['summary'][per] = copytext.summary(P, per)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--period', required=True, help='payload key of the current month, e.g. oct')
    ap.add_argument('--label', required=True, help='tab label of the current month, e.g. 10月')
    ap.add_argument('--month', nargs='+', required=True, help='raw API files covering the current month')
    ap.add_argument('--all', nargs='+', required=True, help='raw API files covering every month on the dashboard')
    ap.add_argument('--labels', required=True)
    ap.add_argument('--sub-to', required=True, help='last submitted date included, YYYY-MM-DD (JST)')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    html = read_html(a.html)
    p = get_payload(html)
    if a.period not in p['roles'][ROLES[0]]['periods']:
        add_month(p, a.period, a.label)
        print(f'added a new tab: {a.label} ({a.period})')
    month_recs, _ = load(*a.month)
    all_recs, raw = load(*a.all)
    month_recs = [r for r in month_recs if r['date'] <= a.sub_to]
    all_recs = [r for r in all_recs if r['date'] <= a.sub_to]
    comments, shine, n_shine = labelled_items(json.load(open(a.labels)), raw, {r['id']: r for r in all_recs})

    rebuild_period(p, a.period, a.label, month_recs, raw, comments, shine, n_shine, a.sub_to)
    rebuild_period(p, 'all', '全期間', all_recs, raw, comments, shine, n_shine, a.sub_to)

    for t in p['summary']['trend']:
        D = p['roles'][t['role']]['periods'][a.period]
        m = next(x for x in t['months'] if x['k'] == a.period)
        m.update(avg=D['role']['avg'], n=D['role']['n'], req=D['meta']['nRoleReq'], com=D['meta']['nRoleComment'])
    tc = next(x for x in p['summary']['trendClinic'] if x['k'] == a.period)
    tc.update(avg=p['summary'][a.period]['clinicAvg'], n=p['summary'][a.period]['nResp'], to=a.sub_to)

    html = set_payload(html, p)
    sub_from = p['summary'][a.period]['from']
    note = (f"{int(sub_from[5:7])}月分（{int(sub_from[5:7])}/{int(sub_from[8:])}〜{int(a.sub_to[5:7])}/{int(a.sub_to[8:])}提出）"
            f"はKOS OpenAPIから直接取得した回答で集計しています（{int(a.sub_to[5:7])}/{int(a.sub_to[8:])}更新）。")
    pat = re.compile(r'\d+月分（[^）]*提出）はKOS OpenAPIから直接取得した回答で集計しています（[^）]*更新）。')
    html = pat.sub(note, html) if pat.search(html) else html.replace('含みません。', '含みません。' + note, 1)
    os.umask(0o077)
    open(a.out, 'w', encoding='utf-8').write(html)
    s = p['summary']
    for per in (a.period, 'all'):
        print(per, f"回答 {s[per]['nResp']}名 / 総評 {s[per]['clinicAvg']:.2f} / 自由記述 {s[per]['comTotal']} / 改善要望 {s[per]['reqTotal']}",
              [(r['role'], r['n'], round(r['avg'], 2)) for r in s[per]['roles']])


if __name__ == '__main__':
    main()
