"""Recompute the published days from KOS data and show where they differ.

    python3 -I pipeline/sales/landing/verify.py --html PAGE.html --work $WORK [--json OUT.json] [--all-fields]

For every day of DAYS_BASE and DAYS_CUR on the page, the day is rebuilt from the API the way build.py
would build it without a 0:00 snapshot (cancellation timing from status + 予約メモ; the page's own
朝の予想 is reused for days marked AmSrc=snapshot, since that number cannot be recomputed). Also checks
売上目標の進捗 (TARGET actual rows = 決済ベース), MONTH, the September 決済 summary and TODAY.

Exit code: 0 = done (differences are reported, not fatal); 2 = a check that must hold failed:
  * a closed month's 決済ベースの売上 (SUMMARY.total / TARGET.prev.total) does not reproduce
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregate  # noqa: E402
import page  # noqa: E402
from data import Raw, month_days  # noqa: E402

CORE = ['visN', 'bookN', 'sameN', 'cancN', 'A', 'Amorning', 'C', 'payC', 'resvV', 'missN', 'avg', 'upS', 'dnS', 'zsum',
        'Aold', 'low']
KPI = ['aov', 'payAov', 'tpp', 'multi', 'nomenuN']
LISTS = ['lead', 'ages', 'ch', 'prep', 'trTot', 'push']


def day_date(lbl, year):
    m, d = map(int, lbl.split('/'))
    return dt.date(year, m, d)


def compare_days(raw, days, year, fields):
    rows, tot = [], collections.defaultdict(lambda: [0, 0])
    for p in days:
        d = day_date(p['date'], year)
        r = aggregate.day_record(raw, d, morning=p['Amorning'] if p['AmSrc'] == 'snapshot' else None, pay_based='payC' in p)
        diff = {}
        for f in fields:
            a = p.get(f) if f not in KPI else p['kpi'].get(f)
            b = r.get(f) if f not in KPI else r['kpi'].get(f)
            if f in LISTS:
                if f == 'push' and a:  # the page's push counts stop at its export time (asof)
                    a, b = a['rows'], b['rows']
                if f in ('ch', 'ages'):
                    a, b = sorted(map(tuple, a or [])), sorted(map(tuple, [x for x in b or [] if x[1]]))
                    a = [x for x in a if x[1]]
            if a is None:
                continue
            ok = a == b or (isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a) >= 1000 and abs(a - b) <= 1)  # yen rounding
            tot[f][0] += ok
            tot[f][1] += 1
            if not ok:
                diff[f] = [a, b]
        rows.append({'date': p['date'], 'src': p['AmSrc'], 'diff': diff, 'pub': {f: p.get(f) for f in ('visN', 'C', 'payC', 'A', 'Amorning')},
                     'new': {f: r.get(f) for f in ('visN', 'C', 'payC', 'A', 'Amorning')}})
    return rows, {f: f'{v[0]}/{v[1]}' for f, v in tot.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--work', default=os.environ.get('WORK', '/tmp/sales-work/landing'))
    ap.add_argument('--json')
    ap.add_argument('--all-fields', action='store_true', help='also compare the 客単価 indicators')
    ap.add_argument('--strict', action='store_true', help='also fail (exit 2) when a 決済ベース day of 売上目標の進捗, or the '
                    '着地結果 (来院ベース) / 決済ベース of a day built by this pipeline, differs from the API')
    a = ap.parse_args()
    raw = Raw(a.work)
    html = open(a.html, encoding='utf-8').read()
    c = page.get_consts(html)
    mon = c.get('MON') or {'y': int(c['TODAY']['label'][:4]), 'by': int(c['TODAY']['label'][:4])}
    fields = CORE + (KPI + LISTS if a.all_fields else [])
    report, fatal = {}, []
    for key, year in (('DAYS_BASE', mon['by']), ('DAYS_CUR', mon['y'])):
        rows, summ = compare_days(raw, c[key], year, fields)
        report[key] = {'days': rows, 'match': summ}
        print(f'== {key}: days matching per field ({len(rows)} days)')
        print('   ' + '  '.join(f'{f} {v}' for f, v in summ.items()))
        for r in rows:
            if r['diff']:
                print(f"   {r['date']:>5} [{r['src']}] " + ', '.join(f'{f} {v[0]}→{v[1]}' for f, v in r['diff'].items() if f in ('visN', 'C', 'payC', 'A', 'Amorning', 'sameN', 'bookN')))
        tp = lambda f: sum(r['pub'][f] or 0 for r in rows)  # noqa: E731
        tn = lambda f: sum(r['new'][f] or 0 for r in rows)  # noqa: E731
        print(f"   total: 来院 {tp('visN')}→{tn('visN')}, 着地結果(来院ベース) {tp('C'):,}→{tn('C'):,}, "
              f"当日来院者基準 {tp('A'):,}→{tn('A'):,}, 予約時点(朝) {tp('Amorning'):,}→{tn('Amorning'):,}"
              + (f", 決済ベース {tp('payC'):,}→{tn('payC'):,}" if any(r['pub']['payC'] for r in rows) else ''))
    # 決済ベースの売上 of the reference month and of the current month so far
    base_days = [day_date(p['date'], mon['by']) for p in c['DAYS_BASE']]
    pay_base = sum(aggregate.pay_day(raw, d) for d in base_days)
    pub_total = c['TARGET']['prev']['total']
    print(f'== 決済ベース {len(base_days)}日: published {pub_total:,} / API {pay_base:,}' + ('  OK' if pub_total == pay_base else '  DIFF'))
    if pub_total != pay_base:
        fatal.append('closed month 決済ベース total differs')
    ym = '%d-%02d' % (mon['y'], int(c['TARGET']['month'].rstrip('月')))
    t_rows = {r[0]: r for r in c['TARGET']['rows'] if r[3] == 'actual'}
    bad = []
    for d in month_days(ym):
        lbl = f'{d.month}/{d.day}'
        if lbl in t_rows and t_rows[lbl][2] != aggregate.pay_day(raw, d):
            bad.append(f'{lbl} {t_rows[lbl][2]:,}→{aggregate.pay_day(raw, d):,}')
    print(f'== TARGET actual rows (決済ベース): {len(t_rows) - len(bad)}/{len(t_rows)} match' + (' — ' + ', '.join(bad) if bad else ''))
    if a.strict:
        if bad:
            fatal.append('TARGET actual rows differ: ' + ', '.join(bad))
        for key in ('DAYS_BASE', 'DAYS_CUR'):
            for r in report[key]['days']:
                p = next(x for x in c[key] if x['date'] == r['date'])
                if 'Cex' in p:  # built or restated by this pipeline: C and payC must reproduce
                    for f in ('C', 'payC'):
                        if f in r['diff']:
                            fatal.append(f"{r['date']} {f} {r['diff'][f][0]}→{r['diff'][f][1]}")
    mc = aggregate.month_chart(raw, base_days)
    mbad = [f'{p[0]}' for p, q in zip(c['MONTH'], mc) if p != q]
    print(f'== MONTH: {len(mc) - len(mbad)}/{len(mc)} rows match' + (' — differ: ' + ', '.join(mbad) if mbad else ''))
    S = c.get('SUMMARY')
    if S:
        pb = collections.Counter()
        for d in base_days:
            for k, v in aggregate.pay_bridge(raw, d).items():
                pb[k] += v
        print(f"== SUMMARY.pay: card {S['pay']['card']:,}/{pb['card']:,} cash {S['pay']['cash']:,}/{pb['cash']:,} "
              f"pre {S['pay']['pre']:,}/{pb['pre']:,} cancel {S['pay']['cancel']:,}/{pb['cancel']:,} ({S['pay']['cancelN']}/{pb['cancelN']}件) "
              f"refund {S['pay']['refund']:,}/{pb['refund']:,}")
        tv = sum(aggregate.visit_total_all(raw, d) for d in base_days)
        print(f"== SUMMARY.totalVisit (来院ベース, 全体): {S['totalVisit']:,} / API {tv:,}")
    if a.json:
        json.dump(report, open(a.json, 'w'), ensure_ascii=False, indent=1)
    if fatal:
        print('FATAL: ' + '; '.join(fatal))
        sys.exit(2)


if __name__ == '__main__':
    main()
