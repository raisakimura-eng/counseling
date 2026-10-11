"""KOS rows -> the data constants embedded in the 着地予想ダッシュボード.

Definitions follow the page's own explanations; see README.md 「集計ルール」 for the list and
for what the API can and cannot reproduce.
"""
import collections
import datetime as dt

import config
from config import RATE, TYPES
from data import (dlabel, excluded, menu_label, money, paid, reserved_at, resv, start, vtype, wd)


def yen(v):
    return f'{round(v):,}'


def pct1(v):
    return f'{v * 100:.1f}%'


def _avg(xs):
    xs = [x for x in xs if x > 0]
    return sum(xs) / len(xs) if xs else 0


def forecast(rows, avg):
    """予約金額 × 来院率 (初診90%・再診95%); メニュー未入力 (予約金額0) is filled with AVG."""
    return sum(RATE[vtype(r)] * (resv(r) or avg) for r in rows)


def proc_tasks(raw, d):
    """施術 (procedure tasks) completed on D, without 診察・麻酔・指名料; keyed by (visitorId)."""
    out = collections.defaultdict(list)
    for t in raw.proc.get(d, []):
        if config.PROC_EXCLUDE.search((t.get('procedureName') or '') + (t.get('title') or '')):
            continue
        out[t['visitorId']].append(t)
    return out


def prod_name(t):
    """Product title without campaign tags and medal emojis: 【ポイント5倍還元】オンダプロ / 🥈オンダプロ -> オンダプロ."""
    import re
    k = t.get('productTitle') or t.get('title') or ''
    return re.sub(r'【[^】]*】|[🥇🥈🥉]', '', k).strip()


def act_label(tasks):
    """Treatments actually done, largest 施術実施額 first: 'オンダプロ ＋ リジュラン'."""
    amt = collections.Counter()
    for t in tasks:
        amt[prod_name(t)] += money(t.get('ticketPriceV2'))
    return ' ＋ '.join(k for k, _ in sorted(amt.items(), key=lambda x: -x[1]))


def cancel_timing(r, d):
    """'same' / 'prev' / 'old' / 'unk' for a cancelled reservation of day D, from status and 予約メモ.

    The API has no cancellation time. NO_SHOW is same-day; otherwise the memo's staff log is read:
    the date stamp (「9/3山﨑」) of the entry that mentions the cancellation, or same-day words
    (当日キャンセル, 来院なく, 無キャン...). Without either the timing is unknown ('unk').
    """
    import re
    if r['reservationStatus'] == 'NO_SHOW':
        return 'same'
    stamp = re.compile(r'^\s*[・☆★◎]?\s*(\d{1,2})/(\d{1,2})(?![\d/])')
    anyd = re.compile(r'(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])')

    def mk(mo, da):
        try:
            x = dt.date(d.year, int(mo), int(da))
        except ValueError:
            return None
        return x if x <= d else None
    cur = None
    for line in (r.get('reservationMemo') or '').split('\n'):
        m = stamp.match(line)
        if m:
            cur = mk(*m.groups())
        if config.CANCEL_LINE.search(line):
            if config.SAME_DAY_WORDS.search(line):
                return 'same'
            x = cur
            if x is None:
                m2 = anyd.search(line)
                x = mk(*m2.groups()) if m2 else None
            if x is None:
                return 'unk'
            n = (d - x).days
            return 'same' if n == 0 else 'prev' if n == 1 else 'old'
    return 'unk'


class Day:
    """Everything about one visit day D, computed once and shared by the outputs."""

    def __init__(self, raw, d, snap=None):
        self.d = d
        rows = raw.sched.get(d, [])
        self.excl = [r for r in rows if excluded(r)]
        rs = [r for r in rows if not excluded(r)]
        self.visited = [r for r in rs if r['reservationStatus'] in config.VISITED]
        live_visitors = {r['visitorId'] for r in rs if r['reservationStatus'] in config.ACTIVE}
        cancelled = [r for r in rs if r['reservationStatus'] in config.CANCELLED]
        # 同じ日の別時間への振替: a cancelled reservation of someone who still has one that day counts once
        self.rebook = [r for r in cancelled if r['visitorId'] in live_visitors]
        self.cancelled = [r for r in cancelled if r['visitorId'] not in live_visitors]
        self.snap = snap
        day0 = dt.datetime.combine(d, dt.time(), raw_tz())
        if snap is not None:
            # 0:00 snapshot of the previous run: a reservation active at 0:00 and cancelled later was
            # cancelled on the day; one booked on the day and cancelled is also a same-day cancellation
            ids = set(snap)
            self.timing = {}
            for r in self.cancelled:
                if r['scheduleId'][:8] in ids or reserved_at(r) >= day0 or r['reservationStatus'] == 'NO_SHOW':
                    self.timing[r['scheduleId']] = 'same'
                else:
                    t = cancel_timing(r, d)
                    self.timing[r['scheduleId']] = 'unk' if t == 'same' else t
        else:
            self.timing = {r['scheduleId']: cancel_timing(r, d) for r in self.cancelled}
        self.same = [r for r in self.cancelled if self.timing[r['scheduleId']] == 'same']
        self.plan = self.visited + self.same
        self.full = self.visited + self.cancelled
        self.day0 = day0
        self.tasks = proc_tasks(raw, d)
        self.raw = raw

    def who(self, r):
        a = self.raw.age_band(r['visitorId'], self.d)
        return vtype(r) + (' ' + a if a else '')


def raw_tz():
    from data import JST
    return JST


def day_record(raw, d, snap=None, morning=None, pay_based=True, fetched_hhmm=None):
    """One element of DAYS_<month>. MORNING = the forecast published at 0:00 for D (if any)."""
    x = Day(raw, d, snap)
    vis, plan, full = x.visited, x.plan, x.full
    by_t = lambda rows, t: [r for r in rows if vtype(r) == t]  # noqa: E731
    avg = _avg(resv(r) for r in plan)
    A = forecast(plan, avg)
    low = sum(RATE[vtype(r)] * resv(r) for r in plan)
    Aold = forecast(full, _avg(resv(r) for r in full))
    morning_rows = [r for r in plan if reserved_at(r) < x.day0]
    Am = forecast(morning_rows, avg)
    C = sum(paid(r) for r in vis)
    resvV = sum(resv(r) for r in vis)
    nomenu = [r for r in vis if resv(r) == 0]
    zeros = [r for r in vis if resv(r) > 0 and paid(r) == 0]
    ups = [r for r in vis if 0 < resv(r) < paid(r)]
    dns = [r for r in vis if 0 < paid(r) < resv(r)]
    upS = sum(paid(r) - resv(r) for r in ups)
    dnS = sum(paid(r) - resv(r) for r in dns)
    zsum = sum(resv(r) for r in zeros)
    rate_gap = sum(resv(r) or avg for r in vis) - A
    fill = sum(paid(r) - avg for r in nomenu)  # 未入力の補完: actual payment instead of the filled average
    typ = []
    for t in TYPES:
        p, v = by_t(plan, t), by_t(vis, t)
        rs_, pd_ = sum(resv(r) for r in v), sum(paid(r) for r in v)
        typ.append({'t': t, 'n': len(p), 'vis': len(v), 'vr': len(v) / len(p) if p else 0, 'assume': RATE[t],
                    'resv': rs_, 'paid': pd_, 'ratio': pd_ / rs_ if rs_ else None})

    def swing(r):
        return {'who': x.who(r), 'menu': menu_label(r), 'act': act_label(x.tasks.get(r['visitorId'], [])),
                'resv': resv(r), 'paid': paid(r), 'diff': paid(r) - resv(r)}
    cand = [r for r in vis if resv(r) > 0 and paid(r) > 0 and paid(r) != resv(r)]
    pos = sorted([r for r in cand if paid(r) > resv(r)], key=lambda r: -(paid(r) - resv(r)))[:4]
    neg = sorted([r for r in cand if paid(r) < resv(r)], key=lambda r: paid(r) - resv(r))[:2]
    sd_all = [r for r in plan if reserved_at(r) >= x.day0]
    sd = [r for r in sd_all if r['reservationStatus'] in config.VISITED]
    lead = collections.Counter()
    for r in vis:
        ra = reserved_at(r)
        if ra is None:
            lead['不明'] += 1
            continue
        n = (d - ra.date()).days
        lead['当日' if n <= 0 else '前日' if n == 1 else '2〜7日前' if n <= 7 else '8〜30日前' if n <= 30 else '31日以上前'] += 1

    def groups(key, names=None):
        g = collections.OrderedDict((n, [n, 0, 0, 0]) for n in names or [])
        for r in vis:
            k = key(r)
            e = g.setdefault(k, [k, 0, 0, 0])
            e[1] += 1
            e[2] += paid(r)
            e[3] += vtype(r) == '初診'
        return list(g.values())
    ages = groups(lambda r: raw.age_band(r['visitorId'], d) or '不明', config.AGE_BANDS)
    ages = [a for a in ages if a[0] != '不明' or a[1]]
    ch = sorted(groups(lambda r: r.get('reservationFunnelName') or '未設定'), key=lambda a: -a[2])
    # 売れた施術: every procedure task of the day (staff included, as on the page), by product title
    tr = collections.defaultdict(lambda: [set(), 0])
    ntask, pts = 0, set()
    for vid, ts in x.tasks.items():
        for t in ts:
            k = prod_name(t)
            tr[k][0].add(vid)
            tr[k][1] += money(t.get('ticketPriceV2'))
            ntask += 1
            pts.add(vid)
    trl = [[k, len(v[0]), round(v[1])] for k, v in tr.items()]
    trTop = sorted(trl, key=lambda a: (-a[2], -a[1]))[:5]
    trCnt = sorted(trl, key=lambda a: (-a[1], -a[2]))[:1]
    # 客単価の内訳
    payers = [r for r in vis if paid(r) > 0]
    nkinds = [len({t.get('productTitle') for t in x.tasks.get(r['visitorId'], [])}) for r in payers]  # kinds as titled in KOS
    single = sum(1 for n in nkinds if n == 1)
    multi = sum(1 for n in nkinds if n >= 2)
    kpi = {'aov': round(C / len(vis)) if vis else 0,
           'aovT': {t: round(sum(paid(r) for r in by_t(vis, t)) / len(by_t(vis, t))) if by_t(vis, t) else 0 for t in TYPES},
           'payAov': round(C / len(payers)) if payers else 0,
           'tpp': round(sum(nkinds) / len(payers), 2) if payers else None,
           'multi': round(multi / len(payers), 3) if payers else 0, 'single': single,
           'nomenu': round(len(nomenu) / len(vis), 3) if vis else 0, 'nomenuN': len(nomenu),
           'nomenuAvg': round(sum(paid(r) for r in nomenu) / len(nomenu)) if nomenu else 0,
           'course': sum(1 for r in vis if paid(r) == 0 and x.tasks.get(r['visitorId']))}
    # プリペイド (現金残高 BALANCE のみ。ポイントは含めない)
    pp = [e for e in raw.prepaid.get(d, []) if e.get('chargingAmountType') == 'BALANCE']
    buys = [e for e in pp if e['chargingType'] == 'CHARGE']
    uses = [e for e in pp if e['chargingType'] == 'PAYMENT']
    cards = collections.Counter((e.get('prepaidCardTitle') or '').replace('NaA Rewards - ', '') for e in buys)
    prep = {'buyN': len(buys), 'buyAmt': sum(money(e.get('chargingAmountV2')) for e in buys),
            'cards': [[k, n] for k, n in cards.most_common()], 'useN': len(uses),
            'useAmt': -sum(money(e.get('chargingAmountV2')) for e in uses)}
    sameT = collections.Counter(vtype(r) for r in x.same)
    vr = {t['t']: t['vr'] for t in typ}
    rec = {
        'date': dlabel(d), 'wd': wd(d), 'label': f'{d.year}年{d.month}月{d.day}日（{wd(d)}）',
        'bookN': len(plan), 'Aold': round(Aold), 'fullN': len(full),
        'bookT': {t: len(by_t(plan, t)) for t in TYPES}, 'visN': len(vis), 'cancN': len(x.cancelled),
        'rebook': len({r['visitorId'] for r in x.rebook}), 'A': round(A), 'low': round(low), 'cal': None, 'C': C, 'resvV': resvV,
        'missN': sum(1 for r in plan if resv(r) == 0), 'avg': round(avg),
        'wf': [['着地予想', round(A)], ['来院率の差', round(rate_gap)], ['未入力の補完', round(fill)],
               ['決済0円', -zsum], ['減額', dnS], ['増額', upS], ['着地結果', C]],
        'wfnotes': ['当日基準の来院予定', f'当日キャンセル{len(x.same)}件', f'未入力{len(nomenu)}件（平均単価{yen(avg)}円で補完）',
                    f'予約金額ありで0円の{len(zeros)}件', f'予約金額より少ない{len(dns)}件', f'予約金額より多い{len(ups)}件', '決済総額'],
        'typ': typ,
        'zeros': [{'who': x.who(r), 'menu': menu_label(r), 'amt': resv(r)} for r in sorted(zeros, key=lambda r: -resv(r))],
        'zsum': zsum, 'swings': [swing(r) for r in pos + neg],
        'upN': len(ups), 'upS': upS, 'dnN': len(dns), 'dnS': dnS,
        'plan': {t: len(by_t(plan, t)) for t in TYPES}, 'visT': {t: len(by_t(vis, t)) for t in TYPES},
        'same': [{'who': vtype(r), 'time': start(r).strftime('%H:%M'), 'menu': menu_label(r), 'amt': resv(r),
                  'noshow': r['reservationStatus'] == 'NO_SHOW'} for r in sorted(x.same, key=start)],
        'sameN': len(x.same),
        'prevN': sum(1 for v in x.timing.values() if v == 'prev'),
        'oldN': sum(1 for v in x.timing.values() if v == 'old'),
        'unkN': sum(1 for v in x.timing.values() if v == 'unk'),
        'sd': {'n': len(sd), 'T': {t: len(by_t(sd, t)) for t in TYPES}, 'paid': sum(paid(r) for r in sd),
               'resv': sum(resv(r) for r in sd), 'zero': sum(1 for r in sd if paid(r) == 0),
               'canc': len(sd_all) - len(sd), 'share': len(sd) / len(vis) if vis else 0,
               'pshare': sum(paid(r) for r in sd) / C if C else 0},
        'Am': round(Am),
        'lead': [[b, lead[b]] for b in config.LEAD_BUCKETS],
        'ages': ages, 'ch': ch, 'hasTr': True, 'hasPrep': True, 'sdPartial': False,
        'trTop': trTop, 'factors': [], 'kpi': kpi, 'trCnt': trCnt,
        'trTot': {'n': ntask, 'amt': round(sum(v[1] for v in tr.values())), 'pts': len(pts)},
        'prep': prep,
        'Amorning': round(morning) if morning is not None else round(Am),
        'AmSrc': 'snapshot' if morning is not None else 'recon',
    }
    rec['factors'] = factors(rec, x, vis, nomenu, zeros, ups, dns, sameT, vr)
    rec['push'] = hpb_sold(raw, d, fetched_hhmm)
    if pay_based:
        pb = pay_bridge(raw, d)
        rec['payC'] = pb['total']
        rec['payNote'] = pay_note(pb, prep, C)
    return rec


def factors(rec, x, vis, nomenu, zeros, ups, dns, sameT, vr):
    out = []
    if ups:
        r = max(ups, key=lambda r: paid(r) - resv(r) if resv(r) else -1)
        act = act_label(x.tasks.get(r['visitorId'], []))
        out.append({'k': '増額', 'v': rec['upS'], 'text': f"予約金額より多い決済が{len(ups)}件。最大は{x.who(r)}で、{menu_label(r)}の予約（{yen(resv(r))}円）に対して"
                    + (f'実際は{act}を受け、' if act else '') + f'{yen(paid(r))}円の決済でした。'})
    if dns:
        r = min(dns, key=lambda r: paid(r) - resv(r))
        act = act_label(x.tasks.get(r['visitorId'], []))
        out.append({'k': '減額', 'v': rec['dnS'], 'text': f"予約金額より少ない決済が{len(dns)}件。最大は{x.who(r)}で、{menu_label(r)}の予約（{yen(resv(r))}円）が"
                    + (f'実際は{act}（{yen(paid(r))}円）でした。' if act else f'{yen(paid(r))}円の決済でした。')})
    nz = sum(1 for r in nomenu if paid(r) == 0)
    out.append({'k': 'メニュー未入力', 'v': rec['wf'][2][1], 'text': (
        f"メニュー未入力の来院{len(nomenu)}件を平均予約単価{yen(rec['avg'])}円で見込みましたが、実際の決済は計{yen(sum(paid(r) for r in nomenu))}円でした（うち{nz}件は決済0円）。"
        if nomenu else 'メニュー未入力の来院はありませんでした。')})
    g = rec['wf'][1][1]
    out.append({'k': '来院率', 'v': g, 'text': f"当日キャンセル{rec['sameN']}件（初診{sameT['初診']}件、再診{sameT['再診']}件）。来院率は初診{pct1(vr['初診'])}（想定90%）・再診{pct1(vr['再診'])}（想定95%）で、全体では予想を{'押し上げ' if g >= 0 else '押し下げ'}ました。"})
    if zeros:
        top = max(zeros, key=resv)
        with_tr = sum(1 for r in zeros if x.tasks.get(r['visitorId']))
        no_tr = len(zeros) - with_tr
        t = f"予約金額があるのに決済0円の来院が{len(zeros)}件（予約金額 計{yen(rec['zsum'])}円）。最大は{x.who(top)}の{menu_label(top)}（{yen(resv(top))}円）です。"
        if with_tr:
            t += f'このうち{with_tr}件は施術を受けており、コースやプリペイドの消化など事前の支払い分と考えられます。'
        if no_tr:
            t += f'{no_tr}件は施術記録がなく、カウンセリングのみで終わった可能性があります。'
        out.append({'k': '決済0円', 'v': -rec['zsum'], 'text': t})
    return sorted(out, key=lambda f: -abs(f['v']))


def hpb_sold(raw, d, asof=None):
    """高単価施術（HPB掲載メニュー）: purchases of the day. 件数 = people, 金額 = 会計金額."""
    rows = []
    for label, rx in config.HPB_MENUS:
        ppl, amt = set(), 0
        for p in raw.purchase.get(d, []):
            if p.get('purchaseItemType') != 'PRODUCT_OPTION' or p.get('purchaseStatus') == 'REFUNDED':
                continue
            if rx.search((p.get('productTitle') or '') + ' ' + (p.get('productOptionTitle') or '')):
                ppl.add(p['visitorId'])
                amt += money((p.get('cost') or {}).get('totalAmount'))
        rows.append([label, len(ppl), amt])
    return {'rows': rows, 'n': sum(r[1] for r in rows), 'amt': sum(r[2] for r in rows), 'asof': asof or '閉院後', 'note': None}


def pay_day(raw, d):
    """決済ベースの売上 of D (whole clinic): 決済履歴 created on D, prepaid payments excluded
    (the money was received when the card was charged), cancellations and refunds subtracted."""
    return sum(money(t['cost']['totalAmount']) for t in raw.tx.get(d, [])
               if t['paymentType'] != 'PREPAID_CARD' and t['status'] in ('APPROVED', 'CANCELED', 'SPENT'))


def pay_bridge(raw, d):
    tx = [t for t in raw.tx.get(d, []) if t['paymentType'] != 'PREPAID_CARD']
    by = lambda st: [t for t in tx if t['status'] == st]  # noqa: E731
    s = lambda ts: sum(money(t['cost']['totalAmount']) for t in ts)  # noqa: E731
    goods = sum(money((p.get('cost') or {}).get('totalAmount')) for p in raw.purchase.get(d, [])
                if p.get('purchaseItemType') == 'ETCETRA_PRODUCT' and p.get('purchaseStatus') != 'REFUNDED')
    return {'total': s(by('APPROVED')) + s(by('CANCELED')) + s(by('SPENT')), 'card': s(t for t in by('APPROVED') if t['paymentType'] == 'CARD'),
            'cash': s(t for t in by('APPROVED') if t['paymentType'] == 'CASH'), 'pre': s(t for t in by('APPROVED') if t['paymentType'] == 'PLATFORM'),
            'cancel': s(by('CANCELED')), 'cancelN': len(by('CANCELED')), 'refund': s(by('SPENT')), 'goods': goods}


def pay_note(pb, prep, C):
    parts = []
    if prep['buyN']:
        parts.append(f"プリペイドの購入{prep['buyN']}件（+{yen(prep['buyAmt'])}円）")
    if prep['useN']:
        parts.append(f"プリペイドでの支払い{prep['useN']}件（−{yen(prep['useAmt'])}円。お金はチャージしたときに受け取り済み）")
    if pb['goods']:
        parts.append(f"物販など（+{yen(pb['goods'])}円）")
    if pb['cancel'] or pb['refund']:
        parts.append(f"決済のキャンセル・返金（−{yen(-(pb['cancel'] + pb['refund']))}円）")
    return ('、'.join(parts) + 'など') if parts else '物販など施術以外の品目と、決済のタイミングのずれ'


# ---------------------------------------------------------------- month-level ----

def visit_total_all(raw, d):
    """来院ベースの売上 of the whole clinic (staff included): 施術決済総額 of all visits of D."""
    return sum(paid(r) for r in raw.sched.get(d, []) if r['reservationStatus'] in config.VISITED)


def month_chart(raw, days):
    """MONTH: [MM.DD, 来院数, 予約金額, 決済額] of every visit (staff included) of the base month."""
    out = []
    for d in days:
        v = [r for r in raw.sched.get(d, []) if r['reservationStatus'] in config.VISITED]
        out.append([d.strftime('%m.%d'), len(v), sum(resv(r) for r in v), sum(paid(r) for r in v)])
    return out


def base_stats(raw, base_days, base_records):
    """Model parameters taken from the base (previous, closed) month."""
    import statistics
    X = [Day(raw, d) for d in base_days]
    coef = {'vrate': {}, 'upsell': {}, 'fill': {}}
    for t in TYPES:
        vis = [r for x in X for r in x.visited if vtype(r) == t]
        plan = [r for x in X for r in x.plan if vtype(r) == t]
        pr = [r for r in vis if resv(r) > 0]
        nm = [r for r in vis if resv(r) == 0]
        coef['vrate'][t] = round(len(vis) / len(plan), 4) if plan else RATE[t]
        coef['upsell'][t] = round(sum(map(paid, pr)) / sum(map(resv, pr)), 3) if pr else 1
        coef['fill'][t] = round(sum(map(paid, nm)) / len(nm)) if nm else 0
    allv = {d: visit_total_all(raw, d) for d in base_days}
    wk = collections.defaultdict(list)
    for d in base_days:
        wk[wd(d)].append(allv[d])
    wavg = {w: round(statistics.mean(v)) for w, v in wk.items()}

    def loo(d, same_wd):
        o = [allv[e] for e in base_days if e != d and (wd(e) == wd(d) or not same_wd)]
        return statistics.mean(o)
    acc = {'wk': round(statistics.mean(abs(allv[d] - loo(d, True)) / allv[d] for d in base_days), 3),
           'flat': round(statistics.mean(abs(allv[d] - loo(d, False)) / allv[d] for d in base_days), 3)}
    R = base_records
    band = statistics.mean(abs(r['C'] - r['Amorning']) / r['Amorning'] for r in R)
    bias = sum(r['C'] for r in R) / sum(r['Amorning'] for r in R) - 1
    sd = {'allN': round(statistics.mean(r['sd']['n'] for r in R), 1), 'allPaid': round(sum(r['sd']['paid'] for r in R) / len(R))}
    sd_wd = {}
    for w in '月火水木金土日':
        rr = [r for r in R if r['wd'] == w]
        if rr:
            sd_wd[w] = {'n': round(statistics.mean(r['sd']['n'] for r in rr), 1),
                        'paid': round(statistics.mean(r['sd']['paid'] for r in rr)), 'days': len(rr)}
    return {'coef': coef, 'wavg': wavg, 'acc': acc, 'band': round(band, 3), 'bias': round(bias, 3), 'sd': sd, 'sd_wd': sd_wd}


def extra(raw, days):
    """EXTRA: 売れた施術 / プリペイド of the base month."""
    tr = collections.defaultdict(lambda: [set(), 0])
    rows = 0
    for d in days:
        for vid, ts in proc_tasks(raw, d).items():
            for t in ts:
                k = prod_name(t)
                tr[k][0].add((vid, d))
                tr[k][1] += money(t.get('ticketPriceV2'))
                rows += 1
    trl = [[k, len(v[0]), round(v[1])] for k, v in tr.items()]
    buys = [(d, e) for d in days for e in raw.prepaid.get(d, []) if e.get('chargingAmountType') == 'BALANCE' and e['chargingType'] == 'CHARGE']
    cards = collections.Counter((e.get('prepaidCardTitle') or '').replace('NaA Rewards - ', '') for _, e in buys)
    amt = collections.Counter()
    for _, e in buys:
        amt[(e.get('prepaidCardTitle') or '').replace('NaA Rewards - ', '')] += money(e.get('chargingAmountV2'))
    ages = collections.Counter(raw.age_band(e.get('visitorId') or e.get('ownerId'), d) or '不明' for d, e in buys)
    used = {(d, u.get('prepaidCardId')) for d in days for u in raw.prepaid.get(d, [])
            if u.get('chargingAmountType') == 'BALANCE' and u['chargingType'] == 'PAYMENT'}
    same = sum(1 for d, e in buys if (d, e.get('prepaidCardId')) in used)
    return {'trTop': sorted(trl, key=lambda a: -a[2])[:10], 'trCnt': sorted(trl, key=lambda a: (-a[1], -a[2]))[:5],
            'trTot': {'amt': round(sum(v[1] for v in tr.values())), 'rows': rows},
            'prepCards': [[k, n, amt[k]] for k, n in cards.most_common()],
            'prepAges': dict(ages.most_common()), 'prepSame': same}


def hpb_booked(rows):
    out = []
    for label, rx in config.HPB_MENUS:
        hits = []
        for r in sorted(rows, key=start):
            titles = [t for t in (r.get('requestedOptionTitles') or []) if rx.search(t)]
            if not titles and any(rx.search(t) for t in r.get('requestedProductTitles') or []):
                titles = r.get('requestedOptionTitles') or r.get('requestedProductTitles')
            if titles:
                import re
                hits.append({'time': start(r).strftime('%H:%M'), 'type': vtype(r),
                             'menu': re.sub(r'\s+', ' ', re.sub(r'【[^】]*価格】', ' ', titles[0])).strip(), 'resv': resv(r), '_id': r['scheduleId']})
        out.append([label, len(hits), hits])
    ids = {h['_id'] for row in out for h in row[2]}
    for row in out:
        for h in row[2]:
            del h['_id']
    by_id = {r['scheduleId']: r for r in rows}
    return {'rows': out, 'n': sum(r[1] for r in out), 'bookings': len(ids), 'resvSum': sum(resv(by_id[i]) for i in ids)}


def today_record(raw, d, base, now_label='0:00時点'):
    """TODAY: the forecast for D from the reservations known at run time (0:00 JST)."""
    import re
    rows = raw.sched.get(d, [])
    pool = [r for r in rows if not excluded(r)]
    active = [r for r in pool if r['reservationStatus'] in config.ACTIVE]
    cancelled = [r for r in pool if r['reservationStatus'] in config.CANCELLED]
    exN = sum(1 for r in rows if excluded(r) and r['reservationStatus'] in config.ACTIVE)
    by_t = lambda rs, t: [r for r in rs if vtype(r) == t]  # noqa: E731
    coef = base['coef']
    byType, cur, cal = {}, 0, 0
    for t in TYPES:
        a = by_t(active, t)
        amt = sum(resv(r) for r in a)
        none = sum(1 for r in a if resv(r) == 0)
        c_raw = RATE[t] * (amt + none * coef['fill'][t])
        c_cal = RATE[t] * (amt * coef['upsell'][t] + none * coef['fill'][t])
        byType[t] = {'n': len(a), 'amt': amt, 'cal': round(c_cal)}
        cur += c_raw
        cal += c_cal
    done = [r for r in active if r['reservationStatus'] in config.VISITED]
    hours = collections.Counter()
    for r in active:
        hours[(start(r).hour, r['reservationStatus'] in config.VISITED)] += 1
    hs = [h for h, _ in hours] or [10]
    hrs = [[f'{h:02d}', hours[(h, True)], hours[(h, False)]] for h in range(min(min(hs), 10), max(max(hs), 18) + 1)]
    cnt = collections.Counter()
    for r in active:  # 予約の多いメニュー: each requested menu (希望施術) counted once per reservation
        for t in set(r.get('requestedOptionTitles') or []):
            if t.startswith('指名料'):
                continue
            t = re.sub(r'\s+', ' ', re.sub(r'【[^】]*】', ' ', t)).strip()
            cnt[t if len(t) <= 30 else t[:29] + '…'] += 1

    def grp(key, order=None):
        g = {}
        for r in active:
            k = key(r)
            e = g.setdefault(k, [k, 0, 0, 0])
            e[1] += 1
            e[2] += resv(r)
            e[3] += vtype(r) == '初診'
        v = list(g.values())
        return sorted(v, key=lambda a: order.index(a[0]) if order and a[0] in order else 99) if order else sorted(v, key=lambda a: -a[2])
    priced = [r for r in active if resv(r) > 0]
    none = len(active) - len(priced)
    wdn = wd(d)
    sdr = base['sd_wd'].get(wdn, {'n': 0, 'paid': 0, 'days': 0})
    fill = coef['fill']
    return {
        'date': dlabel(d), 'label': f'{d.year}年{d.month}月{d.day}日（{wdn}）', 'asof': now_label,
        'active': len(active), 'T': {t: len(by_t(active, t)) for t in TYPES}, 'done': len(done), 'wait': len(active) - len(done),
        'doneT': {t: len(by_t(done, t)) for t in TYPES}, 'cancN': len(cancelled),
        'noshow': sum(1 for r in cancelled if r['reservationStatus'] == 'NO_SHOW'), 'sameN': 0,
        'est': sum(resv(r) for r in priced), 'pricedN': len(priced), 'partN': 0, 'noneN': none,
        'avg': round(_avg(resv(r) for r in active)), 'cur': round(cur), 'cal': round(cal),
        # 総予約数基準: the same forecast on every reservation of the day, cancelled ones included
        'full': round(forecast(active + cancelled, _avg(resv(r) for r in active + cancelled))), 'fullN': len(active) + len(cancelled),
        'exact': True, 'estN': 0, 'band': base['band'], 'fullBias': base.get('fullBias', 0), 'vrate': coef['vrate'], 'byType': byType,
        'hours': hrs, 'topCnt': [{'name': k, 'n': n} for k, n in cnt.most_common(8)],
        'ch': grp(lambda r: r.get('reservationFunnelName') or '未設定'),
        'ages': grp(lambda r: raw.age_band(r['visitorId'], d) or '不明', config.AGE_BANDS + ['不明']),
        'sdRef': {'wd': wdn, 'n': sdr['n'], 'paid': sdr['paid'], 'days': sdr['days'], 'allN': base['sd']['allN'], 'allPaid': base['sd']['allPaid']},
        'resvBase': None, 'calNote': 'upsell', 'bias': base['bias'], 'live': None, 'final': None, 'basis': 'morning',
        'raw': round(cur), 'R1': None, 'prevDay': None, 'morningN': len(active), 'poolN': len(rows), 'activeN': len(active) + exN,
        'scaleNote': (f'{now_label}の予約（{len(active) + len(cancelled) + exN}件。うちキャンセル済み{len(cancelled)}件と、'
                      f'スタッフ・インフルエンサー枠{exN}件を除いて{len(active)}件）を使い、予約金額は予約・来院データの実額を当てています。'
                      f'このあと入る当日予約と、当日のキャンセルは含まれていません。'),
        'finalNote': None, 'hasHistory': True, 'pushBook': hpb_booked(active),
        'fillNote': f"メニュー未入力の{none}件は、前月の未入力の方の実績（初診{yen(fill['初診'])}円・再診{yen(fill['再診'])}円）で補完しています。",
        'coef': coef,
        # 0:00 snapshot: which reservations were active when this forecast was made (first 8 chars of the
        # scheduleId). The next run uses it to find the cancellations made during the day.
        'snap': sorted(r['scheduleId'][:8] for r in active),
    }


def resv_month(raw, d, act, rest_days, base_days, wavg):
    """月末の着地金額（予約者ベース）: reservations already booked for the rest of the month, × 来院率,
    corrected by how the base month's 'booked by the same day' reservations turned into results."""
    cut = d  # reservations booked before D 0:00 (as known at the run)
    from data import JST
    t0 = dt.datetime.combine(cut, dt.time(), JST)
    rows = [r for e in rest_days for r in raw.sched.get(e, []) if not excluded(r) and reserved_at(r) < t0]
    P = sum(RATE[vtype(r)] * resv(r) for r in rows)
    k = cut.day  # same position in the base month
    b_rest = [e for e in base_days if e.day >= k]
    if b_rest:
        b0 = dt.datetime.combine(b_rest[0], dt.time(), JST)
        b_rows = [r for e in b_rest for r in raw.sched.get(e, []) if not excluded(r) and reserved_at(r) < b0]
        bP = sum(RATE[vtype(r)] * resv(r) for r in b_rows)
        bC = sum(visit_total_all(raw, e) for e in b_rest)
        ratio = bC / bP if bP else 1
    else:
        b_rows, ratio = [], 1
    return {'act': act, 'Pnow': round(P), 'n': len(rows), 'resv': sum(resv(r) for r in rows), 'ratio': round(ratio, 3),
            'floor': round(act + P), 'land': round(act + P * ratio), 'wk': round(act + sum(wavg[wd(e)] for e in rest_days)),
            'asof': dlabel(d - dt.timedelta(days=1)), 'days': len(rest_days), 'sepN': len(b_rows)}


def target(raw, ym, today, today_cur, goal, base_stats_, morning, prev_total, prev_label, base_days):
    from data import month_days
    days = month_days(ym)
    rows = []
    for e in days:
        if e < today:
            rows.append([dlabel(e), wd(e), pay_day(raw, e), 'actual'])
        elif e == today:
            rows.append([dlabel(e), wd(e), today_cur, 'today'])
        else:
            rows.append([dlabel(e), wd(e), base_stats_['wavg'][wd(e)], 'proj'])
    act = sum(r[2] for r in rows if r[3] == 'actual')
    rest = [e for e in days if e >= today]
    return {'target': goal, 'days': len(days), 'rows': rows, 'wavg': base_stats_['wavg'], 'acc': base_stats_['acc'],
            'month': f'{int(ym[5:])}月', 'prev': {'month': prev_label, 'total': prev_total}, 'morning': morning,
            'resvMonth': resv_month(raw, today, act, rest, base_days, base_stats_['wavg']) if rest else None}
