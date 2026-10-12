"""Rebuild the 着地予想ダッシュボード from the published page + KOS data.

    python3 -I pipeline/sales/landing/build.py --html CURRENT.html --work $WORK --out NEW.html
        [--today YYYY-MM-DD] [--targets pipeline/sales/targets.json]

--today is the new day (JST) whose forecast is made; default = today in JST. The job runs at 0:00,
so "today" has just started and "yesterday" has just closed.

What changes (everything else on the page is kept):
  * yesterday's day record is computed and added to DAYS_CUR (着地結果 = 決済; 予約時点の予想 = the
    forecast this page published at 0:00 yesterday, TODAY.cur; 当日キャンセル = reservations that were
    active at that 0:00 snapshot (TODAY.snap) and are cancelled now). Missing earlier days of the month
    are filled in too (without a snapshot: cancellation timing from the 予約メモ, see aggregate.py).
  * TODAY = forecast for --today from the reservations known now; TARGET = 売上目標の進捗.
  * On the 1st of a month the finished month moves to DAYS_BASE (the reference month), MONTH / EXTRA and
    the model coefficients (TODAY.coef) are recomputed from it, and the new month starts empty.
  * 「9月まとめ」 (SUMMARY, written by hand) is kept as it is. When a month is closed, its 「◯月まとめ」 tab is
    added to SUMMARIES: the numbers are computed here, the sentences come from --summary. Without them
    the numbers are written to --summary-todo and the build stops (exit code 4).
The current month's sales target must be in --targets, otherwise the build stops (exit code 3).
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregate  # noqa: E402
import config  # noqa: E402
import page  # noqa: E402
from data import JST, Raw, dlabel, month_days, wd  # noqa: E402

TARGETS = os.path.join(os.path.dirname(HERE), 'targets.json')
from config import LEGACY_SUMMARY  # noqa: E402
TEXT_TEMPLATE = {
    'cmpNote': '', 'weekNote': '',
    'issues': [{'tag': '', 'text': ''} for _ in range(5)],
    'okr': {'objective': '', 'targets': {'ratio': '', 'morning': '', 'multi': '', 'dn': '', 'course': '', 'same': ''}, 'note': ''},
}


class NeedSummary(Exception):
    pass


def missing_text(t, tpl=TEXT_TEMPLATE, path='text'):
    """Paths of the sentences that are still empty (or missing) in a まとめ text block."""
    out = []
    if isinstance(tpl, dict):
        if not isinstance(t, dict):
            return [path]
        for k, v in tpl.items():
            out += missing_text(t.get(k), v, f'{path}.{k}')
    elif isinstance(tpl, list):
        if not isinstance(t, list) or len(t) != len(tpl):
            return [f'{path} ({len(tpl)}件必要)']
        for i, (x, v) in enumerate(zip(t, tpl)):
            out += missing_text(x, v, f'{path}[{i}]')
    elif not (isinstance(t, str) and t.strip()):
        out.append(path)
    return out


def next_ym(ym):
    y, m = map(int, ym.split('-'))
    return f'{y + m // 12}-{m % 12 + 1:02d}'


def label_date(lbl, year):
    m, d = map(int, lbl.split('/'))
    return dt.date(year, m, d)


def ym_of(d):
    return d.strftime('%Y-%m')


def base_from_page(consts):
    """Parameters of the reference month, read from the page's own data (DAYS_BASE, MONTH)."""
    R = consts['DAYS_BASE']
    core = lambda r: r['C'] - r.get('Cex', 0)  # noqa: E731  (the forecast does not include excluded visits)
    div = aggregate.div
    band = statistics.mean(div(abs(core(r) - r['Amorning']), r['Amorning']) for r in R)
    bias = div(sum(core(r) for r in R), sum(r['Amorning'] for r in R), 1) - 1
    sd_wd = {}
    for w in '月火水木金土日':
        rr = [r for r in R if r['wd'] == w]
        if rr:
            sd_wd[w] = {'n': round(statistics.mean(r['sd']['n'] for r in rr), 1),
                        'paid': round(statistics.mean(r['sd']['paid'] for r in rr)), 'days': len(rr)}
    M = consts['MONTH']
    by = consts['MON']['by']
    wds = {m[0]: wd(dt.date(by, int(m[0][:2]), int(m[0][3:]))) for m in M}
    wk = {}
    for m in M:
        wk.setdefault(wds[m[0]], []).append(m[3])

    def loo(m, same):
        o = [x[3] for x in M if x is not m and (wds[x[0]] == wds[m[0]] or not same)]
        return statistics.mean(o)
    return {'coef': consts['TODAY']['coef'], 'band': round(band, 3), 'bias': round(bias, 3),
            'fullBias': round(statistics.mean(div(core(r) - r['Aold'], r['Aold']) for r in R), 3),
            'sd': {'allN': round(statistics.mean(r['sd']['n'] for r in R), 1), 'allPaid': round(sum(r['sd']['paid'] for r in R) / len(R))},
            'sd_wd': sd_wd, 'wavg': {w: round(statistics.mean(v)) for w, v in wk.items()},
            'acc': {'wk': round(statistics.mean(div(abs(m[3] - loo(m, True)), m[3]) for m in M if sum(1 for x in M if wds[x[0]] == wds[m[0]]) > 1), 3),
                    'flat': round(statistics.mean(div(abs(m[3] - loo(m, False)), m[3]) for m in M), 3)}}


def seed(consts):
    """First run on the page as published before automation: give it MON and TODAY.coef."""
    cur = consts['DAYS_CUR'][0]['date'] if consts['DAYS_CUR'] else consts['TARGET']['rows'][0][0]
    b = int(consts['DAYS_BASE'][0]['date'].split('/')[0])
    c = int(cur.split('/')[0])
    y = int(consts['TODAY']['label'][:4])
    mon = {'y': y, 'b': b, 'c': c, 'by': y if b <= c else y - 1, 'calib': '9/1〜9/26' if b == 9 else f'{b}/1〜{b}/{len(consts["DAYS_BASE"])}'}
    T = consts['TODAY']
    if 'coef' not in T:
        # the values the published page used (TODAY.vrate, fillNote, 「初診 ×1.227、再診 ×1.101」)
        T['coef'] = {'vrate': T['vrate'], 'upsell': {'初診': 1.227, '再診': 1.101}, 'fill': {'初診': 23470, '再診': 6369}}
    if 'coefAll' not in T:
        # 補正ロジックの予想 of the day records (「予約金額から決済への倍率 初診 1.01、再診 1.08」「補完単価 23,376円・7,349円」)
        T['coefAll'] = {'vrate': T['vrate'], 'upsell': {'初診': 1.01, '再診': 1.08}, 'fill': {'初診': 23376, '再診': 7349}}
    return mon


def gen_texts(consts, base_days_n, today):
    mon = consts['MON']
    b, c = mon['b'], mon['c']
    cur = consts['DAYS_CUR']
    snap = [d['date'] for d in cur if d['AmSrc'] == 'snapshot']
    recon = [d['date'] for d in cur if d['AmSrc'] != 'snapshot']
    ex = consts['TODAY'].get('_excl', {})
    parts = []
    if snap:
        parts.append(f'{snap[0]}〜{snap[-1]}は実際に朝お出しした予想' if len(snap) > 1 else f'{snap[0]}は実際に朝お出しした予想')
    if recon:
        parts.append(f'{recon[0]}〜{recon[-1]}は予約登録日から朝の時点の予約を再現しています' if len(recon) > 1 else f'{recon[0]}は予約登録日から朝の時点の予約を再現しています')
    g = consts['TARGET']
    ca = consts['TODAY']['coefAll']
    return {
        'sub': f'（差額＝実決済 − 予約時点の予想。来院率 初診90%・再診95%。メニュー未入力は{b}月の未入力の方の実績で補完）',
        'goalFoot': f'予約データのない日は、{b}月の同じ曜日の平均で見込んでいます。日割り目標は、{g["days"]}日すべて営業する前提で等分しています。',
        'cmpFoot': ('、'.join(parts) + '。') if parts else f'{c}月はまだ実績がありません。',
        'tbaseSub': f'{mon["calib"]}の実績から算出',
        'monthHead': f'{b}月の予約金額と決済額（来院者のみ）',
        'fixFill': f"初診 {ca['fill']['初診']:,}円、再診 {ca['fill']['再診']:,}円",
        'fixMult': f"初診 {ca['upsell']['初診']}、再診 {ca['upsell']['再診']}",
        'fixMultNote': f'メニュー入力済みの来院者の{b}月平均です。',
        **({'fixHigh': f"（{b}月は{ca['high'][0]}件、計{ca['high'][1]:,}円が決済0円）"} if ca.get('high') else {}),
        'footPast': (f'データ：KOS OpenAPI（予約・決済・購入・施術・プリペイドの統計）から自動で集計しています（{today.month}/{today.day} 0:00更新）。'
                     f'スタッフ（患者カテゴリ「NaA+HPMS」）と、インフルエンサー・PR枠（カテゴリ「インフルエンサー」ほか）の来院は、予想・客単価などの分析から除いています'
                     + (f'（{c}月：スタッフ{ex.get("staff", [0, 0])[0]}件・決済{ex.get("staff", [0, 0])[1]:,}円、インフルエンサー・PR{ex.get("influencer", [0, 0])[0]}件・決済{ex.get("influencer", [0, 0])[1]:,}円）' if ex else '')
                     + '。ただし、これらの来院で実際に支払われた金額（自費分）は着地結果（来院ベース）に含めています。売上目標の進捗は、これらを含むクリニック全体の決済額で計算しています。'
                     '予約時点の予想は、毎日0:00時点の予約から出した予想です（それより前の日は予約登録日から再現）。当日キャンセルは、0:00時点で有効だった予約のうち、その日にキャンセル・ノーショーになったものです（0:00時点の記録がない日は、予約状態「ノーショー」と予約メモの記載から判定）。'
                     '同じ日の別時間への振替は来院として数えています。売れた施術は施術実施額（施術チケット決済金額）で集計し、診察・麻酔・指名料は除いています。患者名は表示していません。'),
        'footToday': ('データ：着地結果・客単価・要因の分析は、スタッフとインフルエンサー・PR枠の来院を除いた数字です。売上目標の進捗は、全体の決済額で計算しています。'
                      f'KOS OpenAPI の予約データ（{today.month}/{today.day} 0:00時点）。来院予定は、予約・来院・完了の予約（同じ日の振替は1件として数える）です。患者名は表示していません。'),
    }


def excl_counts(raw, days):
    out = {}
    from data import excluded, paid
    for d in days:
        for r in raw.sched.get(d, []):
            k = excluded(r)
            if k and r['reservationStatus'] in ('COMPLETED', 'IN_PROGRESS'):
                e = out.setdefault(k, [0, 0])
                e[0] += 1
                e[1] += paid(r)
    return out


def build(html, raw, today, targets, summary_text=None):
    consts = page.get_consts(html)
    if not page.is_migrated(html):
        mon = seed(consts)
        html = page.migrate(html, mon)
        consts['MON'] = mon
    html = page.migrate_summaries(html)
    consts.setdefault('SUMMARIES', [])
    mon = consts['MON']
    T0 = consts['TODAY']
    yday = today - dt.timedelta(days=1)
    cur_ym = f'{mon["y"]}-{mon["c"]:02d}'
    # 1. close the days of the current month up to yesterday (append-only; yesterday is always recomputed)
    have = {d['date'] for d in consts['DAYS_CUR']}
    days_cur = [e for e in month_days(cur_ym) if e <= yday]
    recs = {d['date']: d for d in consts['DAYS_CUR']}
    morning = dict(consts['TARGET'].get('morning') or {})
    for e in days_cur:
        if dlabel(e) in have and e != yday:
            continue
        if not raw.sched.get(e):
            raise SystemExit(f'STOP: no KOS reservation data for {e} in $WORK/raw; fetch it first')
        snap = T0.get('snap') if T0.get('date') == dlabel(e) else None
        m = T0['cur'] if T0.get('date') == dlabel(e) else morning.get(dlabel(e))
        recs[dlabel(e)] = aggregate.day_record(raw, e, snap=snap, morning=m, pay_based=True)
        recs[dlabel(e)]['cal'] = round(cal_of(raw, e, T0['coefAll']))
    consts['DAYS_CUR'] = [recs[k] for k in sorted(recs, key=lambda s: tuple(map(int, s.split('/'))))]
    # published days made before the excluded visits' own payments were counted: add them once
    for key, year in (('DAYS_BASE', mon['by']), ('DAYS_CUR', mon['y'])):
        for rec in consts[key]:
            if 'Cex' not in rec:
                restate(raw, rec, label_date(rec['date'], year))
    # 2. month rollover: today is in a new month -> the finished month becomes the reference month
    if ym_of(today) != cur_ym:
        if len(consts['DAYS_CUR']) != len(month_days(cur_ym)):
            raise SystemExit(f'STOP: {cur_ym} is not complete ({len(consts["DAYS_CUR"])} days); not rolling over')
        bdays = month_days(cur_ym)
        consts['DAYS_BASE'] = consts['DAYS_CUR']
        consts['DAYS_CUR'] = []
        consts['MONTH'] = aggregate.month_chart(raw, bdays)
        consts['EXTRA'] = aggregate.extra(raw, bdays)
        bs = aggregate.base_stats(raw, bdays, consts['DAYS_BASE'])
        T0['coef'], T0['coefAll'] = bs['coef'], bs['coefAll']
        mon = {'y': today.year, 'b': bdays[0].month, 'c': today.month, 'by': bdays[0].year,
               'calib': f'{bdays[0].month}/1〜{bdays[0].month}/{bdays[-1].day}'}
        consts['MON'] = mon
        morning = {}
        prev_total = sum(aggregate.pay_day(raw, e) for e in bdays)
    else:
        bdays = [label_date(d['date'], mon['by']) for d in consts['DAYS_BASE']]
        prev_total = consts['TARGET']['prev']['total']
    base = base_from_page(consts)
    # 3. today's forecast and the sales target
    ym = ym_of(today)
    goal = targets.get(ym)
    if not goal:
        sys.stderr.write(f'STOP: no sales target for {ym} in targets.json. Ask for it and add "{ym}": <yen>.\n')
        sys.exit(3)
    T = aggregate.today_record(raw, today, base)
    T['coefAll'] = T0['coefAll']
    T['_excl'] = {k: v for k, v in excl_counts(raw, [label_date(d['date'], mon['y']) for d in consts['DAYS_CUR']]).items()}
    morning[dlabel(today)] = T['cur']
    consts['TODAY'] = T
    consts['TARGET'] = aggregate.target(raw, ym, today, T['cur'], goal, base, morning, prev_total, f'{mon["b"]}月', bdays)
    # 4. 「◯月まとめ」 of the reference month, once it is closed (numbers here, sentences from SUMMARY_TEXT)
    base_ym = f"{mon['by']}-{mon['b']:02d}"
    if base_ym != LEGACY_SUMMARY and base_ym not in {s_['key'] for s_ in consts['SUMMARIES']}:
        nym = next_ym(base_ym)
        S = aggregate.month_summary(raw, base_ym, consts['DAYS_BASE'], targets.get(base_ym),
                                    {'label': f'{int(nym[5:])}月', 'target': targets.get(nym), 'days': len(month_days(nym))})
        st = summary_text if summary_text and summary_text.get('month') == base_ym else None
        if st is None or missing_text(st.get('text')):
            raise NeedSummary({'month': base_ym, 'label': S['label'], 'numbers': S, 'facts': aggregate.summary_facts(S),
                               'missing': missing_text((st or {}).get('text')),
                               'text': (st or {}).get('text') or json.loads(json.dumps(TEXT_TEMPLATE))})
        S['text'] = st['text']
        consts['SUMMARIES'].append(S)
    # 5. write
    texts = gen_texts(consts, len(bdays), today)
    del T['_excl']
    out = page.set_consts(html, {k: consts[k] for k in ['DAYS_BASE', 'DAYS_CUR', 'MON', 'MONTH', 'TODAY', 'EXTRA', 'TARGET', 'SUMMARIES']})
    out = page.set_gen(out, texts)
    out = page.set_month_svg_label(out, f'{mon["b"]}月1日から{len(consts["MONTH"])}日の日別、来院者の予約金額と決済額')
    return out, consts


def restate(raw, rec, d):
    """着地結果（来院ベース）を「除外来院の自費分を含む」定義にそろえる。足す額 = API の新しい定義の値 − 公開値
    (the published value already held part of it on days where the page had kept a paying influencer / staff visit)."""
    from data import excluded, paid
    if not raw.sched.get(d):
        raise SystemExit(f'STOP: no KOS reservation data for {d} in $WORK/raw (needed to restate {rec["date"]}); '
                         f'fetch that month first (daily.py does this)')
    x = aggregate.Day(raw, d)
    exv = [r for r in x.excl if r['reservationStatus'] in ('COMPLETED', 'IN_PROGRESS')]
    amount = sum(paid(r) for r in exv)
    new_c = sum(paid(r) for r in x.visited) + amount
    aggregate.add_excluded(rec, amount, len(exv), sum(1 for r in exv if paid(r) > 0), step=new_c - rec['C'])
    if 'payC' in rec:  # the published value stopped at the export time of that evening; use the closed day
        pb = aggregate.pay_bridge(raw, d)
        if pb['total'] != rec['payC']:
            rec['payC'] = pb['total']
            rec['payNote'] = aggregate.pay_note(pb, rec['prep'], rec['C'])


def cal_of(raw, d, coef):
    """補正ロジックの予想: 来院予定 × 前月の来院率 × (予約金額 × 前月の上乗せ率, 未入力は前月の未入力の実績)."""
    x = aggregate.Day(raw, d)
    from data import resv, vtype
    return sum(coef['vrate'][vtype(r)] * (resv(r) * coef['upsell'][vtype(r)] if resv(r) else coef['fill'][vtype(r)]) for r in x.plan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--work', default=os.environ.get('WORK', '/tmp/sales-work/landing'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--today', help='JST date of the new day (default: today in JST)')
    ap.add_argument('--targets', default=TARGETS)
    ap.add_argument('--summary', help='summary_todo.json whose "text" has been written (makes the 月まとめ tab)')
    ap.add_argument('--summary-todo', help='where to write the numbers when a 月まとめ is needed (default $WORK/summary_todo.json)')
    a = ap.parse_args()
    os.umask(0o077)
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    html = open(a.html, encoding='utf-8').read()
    targets = config.load_targets(a.targets)
    st = json.load(open(a.summary)) if a.summary else None
    try:
        out, c = build(html, Raw(a.work), today, targets, st)
    except NeedSummary as e:
        todo = a.summary or a.summary_todo or os.path.join(a.work, 'summary_todo.json')
        json.dump(e.args[0], open(todo, 'w'), ensure_ascii=False, indent=1)
        miss = e.args[0]['missing']
        sys.stderr.write(f"SUMMARY NEEDED: {e.args[0]['label']}まとめの文章を {todo} の \"text\" に書いてから --summary {todo} で作り直す"
                         + (f"（未記入: {', '.join(miss[:8])}{' ほか' if len(miss) > 8 else ''}）" if a.summary else '') + '\n')
        sys.exit(4)
    open(a.out, 'w', encoding='utf-8').write(out)
    t = c['TARGET']
    act = [r for r in t['rows'] if r[3] == 'actual']
    print(f"built {a.out}: {c['MON']['c']}月 {len(c['DAYS_CUR'])}日分, 本日{c['TODAY']['date']}の予想 {c['TODAY']['cur']:,}円"
          f"（予約{c['TODAY']['active']}件）, 月の実績 {sum(r[2] for r in act):,}円 / 目標 {t['target']:,}円")


if __name__ == '__main__':
    main()
