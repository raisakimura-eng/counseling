"""「この日の分析」: numbers and facts about the day that the 0:30 run has just closed, for a Slack post.

    python3 -I pipeline/sales/landing/analysis.py --html NEW.html --work $WORK --day YYYY-MM-DD --out $WORK/daily_analysis.json

Nothing is added to the page. The daily job's Claude writes the Slack post from this file
(guidelines: README.md 「Slack 投稿文の指針」). The file holds no patient names or chart numbers.
Past months' sales for item 6 are read from the API (one range query per month, cached in $WORK/raw).
"""
import argparse
import collections
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
from data import JST, Raw, dlabel, excluded, jst, menu_label, money, paid, resv, vtype, wd  # noqa: E402

URL = 'https://naaclinic.netlify.app'


def yen(v):
    return f'{round(v):,}円'


def pct(v, d=1):
    return f'{v * 100:.{d}f}%' if v is not None else '—'


def norm(t):
    import re
    return re.sub(r'【[^】]*】|[🥇🥈🥉]|\s', '', t or '')


def not_booked(name, req):
    """A treatment counts as added when no booked product name is part of it (or it of one): ザーフ vs ウルセラ+ザーフ."""
    n = norm(name)
    return bool(n) and not any(q and (q in n or n in q) for q in req)


def period_total(cli_holder, work, ym, last_day):
    """決済ベースの売上 of month YM from the 1st to day LAST_DAY (inclusive); cached."""
    import fetch
    path = os.path.join(work, 'raw', 'period_totals.json')
    cache = json.load(open(path)) if os.path.exists(path) else {}
    key = f'{ym}:{last_day}'
    if key not in cache:
        y, m = map(int, ym.split('-'))
        start = dt.date(y, m, 1)
        try:
            end = dt.date(y, m, last_day) + dt.timedelta(days=1)
        except ValueError:  # the month is shorter: take the whole month
            end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        if 'cli' not in cli_holder:
            cli_holder['cli'] = fetch.Client()
        rows = cli_holder['cli'].fetch_all(fetch.KINDS['transaction'][0], {'createdTimeUtcFrom': fetch.utc(start), 'createdTimeUtcTo': fetch.utc(end)})
        cache[key] = sum(money(t['cost']['totalAmount']) for t in rows
                         if t['paymentType'] != 'PREPAID_CARD' and t['status'] in ('APPROVED', 'CANCELED', 'SPENT'))
        json.dump(cache, open(path, 'w'))
    return cache[key]


def analyse(raw, consts, day, work, targets, n_past=6):
    lbl = dlabel(day)
    # the closed day is in DAYS_CUR, or in DAYS_BASE on the 1st (the month has just rolled over)
    in_cur = any(r['date'] == lbl for r in consts['DAYS_CUR'])
    mlist = consts['DAYS_CUR'] if in_cur else consts['DAYS_BASE']
    prev_list = consts['DAYS_BASE'] if in_cur else []
    rec = next(r for r in mlist if r['date'] == lbl)
    x = aggregate.Day(raw, day)
    vis = x.visited
    by_vid = collections.defaultdict(list)
    for r in vis:
        by_vid[r['visitorId']].append(r)
    pp = [e for e in raw.prepaid.get(day, []) if e.get('chargingAmountType') == 'BALANCE']
    buyers = collections.Counter()
    for e in pp:
        if e['chargingType'] == 'CHARGE':
            buyers[e.get('visitorId') or e.get('ownerId')] += money(e.get('chargingAmountV2'))
    pb = aggregate.pay_bridge(raw, day)
    avg = aggregate._avg(resv(r) for r in x.plan)
    payC = rec.get('payC')
    # 1. 予想と実績の差の理由 (寄与額)
    contrib = {
        '当日予約（当日に入った予約の決済）': rec['sd']['paid'],
        '当日キャンセル（予想に入っていた分）': -round(sum(config.RATE[s['who']] * (s['amt'] or avg) for s in rec['same'])),
        '増額（予約金額より多い決済）': rec['upS'],
        '減額（予約金額より少ない決済）': rec['dnS'],
        '決済0円（予約金額あり）': -rec['zsum'],
        'メニュー未入力の補完との差': rec['wf'][2][1] if rec['wf'][2][0] == '未入力の補完' else 0,
        'スタッフ・PR枠の自費': rec.get('Cex', 0),
        'プリペイド販売（決済ベースのみ）': rec['prep']['buyAmt'],
        'プリペイドでの支払い（決済ベースから除く）': -rec['prep']['useAmt'],
        '物販など': pb['goods'],
        '決済の取消・返金': pb['cancel'] + pb['refund'],
    }
    hp = rec.get('push') or {}
    cases = []
    cand = [r for r in vis if resv(r) > 0 and paid(r) != resv(r)]
    for r in sorted(cand, key=lambda r: -abs(paid(r) - resv(r)))[:2]:
        ts = x.tasks.get(r['visitorId'], [])
        req = {norm(t) for t in r.get('requestedProductTitles') or []}
        act = aggregate.act_label(ts)
        added = sorted({aggregate.prod_name(t) for t in ts if not_booked(aggregate.prod_name(t), req)})
        cases.append({'who': x.who(r), '予約メニュー': menu_label(r), '予約金額': resv(r), '実際の施術': act or '施術記録なし',
                      '予約になかった施術': added, '決済額': paid(r), '差': paid(r) - resv(r),
                      'プリペイド購入': buyers.get(r['visitorId'], 0)})
    item1 = {'朝の予想（0:00時点の予約）': rec['Amorning'], '着地結果（来院ベース）': rec['C'], '着地結果（決済ベース）': payC,
             '差（来院ベース − 朝の予想）': rec['C'] - rec['Amorning'],
             '差（決済ベース − 朝の予想）': payC - rec['Amorning'] if payC is not None else None,
             '寄与額（大きい順）': sorted(([k, v] for k, v in contrib.items() if v), key=lambda kv: -abs(kv[1])),
             '高単価施術（HPB掲載メニュー）の販売': {'件数': hp.get('n', 0), '金額': hp.get('amt', 0),
                                           '内訳': [[r[0], r[1], r[2]] for r in hp.get('rows', []) if r[1]]},
             '目立ったケース': cases}
    # 2. 当日キャンセル
    item2 = {'当日キャンセル': rec['sameN'], '来院予定': rec['bookN'], '当日キャンセル率': round(rec['sameN'] / rec['bookN'], 3) if rec['bookN'] else None,
             '判定方法': '0:00時点の予約一覧との差' if rec.get('sameSrc') == 'snapshot' else '予約状態と予約メモ（0:00の記録なし）',
             'うちノーショー': sum(1 for s in rec['same'] if s['noshow']),
             '前日・それ以前のキャンセル': rec['prevN'] + rec['oldN'], '時期不明のキャンセル': rec['unkN']}
    # 3. 2施術以上の割合
    month = [r for r in mlist if tuple(map(int, r['date'].split('/'))) <= (day.month, day.day)]
    order = sorted((r['kpi']['multi'] for r in month), reverse=True)
    seq = prev_list + month
    last7 = [r['kpi']['multi'] for r in seq[-7:]]
    item3 = {'2施術以上の割合': rec['kpi']['multi'], '当月内の順位': [order.index(rec['kpi']['multi']) + 1, len(order)],
             '7日移動平均': round(statistics.mean(last7), 3), '当月平均': round(statistics.mean(r['kpi']['multi'] for r in month), 3)}
    # 4. メニュー未入力・決済0円
    item4 = {'メニュー未入力の割合': rec['kpi']['nomenu'], 'メニュー未入力の来院': rec['kpi']['nomenuN'],
             '決済0円の来院': sum(1 for r in vis if paid(r) == 0),
             'うち施術あり（コース・プリペイド消化とみられる）': rec['kpi']['course']}
    # 5. プリペイド購入率・再診のオプション追加率
    vis_ids = {r['visitorId'] for r in vis}
    rep = [r for r in vis if vtype(r) == '再診' and resv(r) > 0]
    rep_add = [r for r in rep if any(not_booked(aggregate.prod_name(t), {norm(p) for p in r.get('requestedProductTitles') or []})
                                     for t in x.tasks.get(r['visitorId'], []))]
    item5 = {'プリペイド購入率': round(len(set(buyers) & vis_ids) / len(vis), 3) if vis else None,
             'プリペイド購入（件・金額）': [rec['prep']['buyN'], rec['prep']['buyAmt']],
             '再診のオプション追加率': round(len(rep_add) / len(rep), 3) if rep else None,
             '再診（メニュー入力あり）の来院': len(rep), 'うちオプション追加': len(rep_add)}
    # 6. 月の進捗
    ym = day.strftime('%Y-%m')
    from data import month_days
    act = sum(aggregate.pay_day(raw, e) for e in month_days(ym) if e <= day)
    goal = targets.get(ym)
    days_in = len(month_days(ym))
    holder, past = {}, []
    for k in range(1, n_past + 1):
        mm = day.year * 12 + day.month - 1 - k
        pym = f'{mm // 12}-{mm % 12 + 1:02d}'
        try:
            past.append([pym, period_total(holder, work, pym, day.day)])
        except Exception as e:  # noqa: BLE001 — a missing past month must not stop the analysis
            past.append([pym, None, str(e)[:80]])
    ranked = sorted([v for _, v, *__ in past if v is not None] + [act], reverse=True)
    item6 = {'月の実績（決済ベース、1日〜当日）': act, '目標': goal, '目標比': round(act / goal, 3) if goal else None,
             '日割り累計に対して': round(act / (goal / days_in * day.day), 3) if goal else None,
             '過去の月の同じ期間': past, '順位': [ranked.index(act) + 1, len(ranked)]}
    # 7. 曜日の傾向（来院ベース）
    w = wd(day)
    same_cur = [r['C'] for r in month if r['wd'] == w and r['date'] != lbl]
    same_base = [r['C'] for r in prev_list if r['wd'] == w]
    wk = lambda rs, wkend: [r['C'] for r in rs if (r['wd'] in '土日') == wkend]  # noqa: E731
    item7 = {'曜日': w, 'この日（来院ベース）': rec['C'],
             '当月の同じ曜日の平均（この日を除く）': round(statistics.mean(same_cur)) if same_cur else None,
             '前月の同じ曜日の平均': round(statistics.mean(same_base)) if same_base else None,
             '当月の平日平均': round(statistics.mean(wk(month, False))) if wk(month, False) else None,
             '当月の土日平均': round(statistics.mean(wk(month, True))) if wk(month, True) else None,
             '前月の平日平均': round(statistics.mean(wk(prev_list, False))) if wk(prev_list, False) else None,
             '前月の土日平均': round(statistics.mean(wk(prev_list, True))) if wk(prev_list, True) else None}
    # 8. データのチェック
    rows = raw.sched.get(day, [])
    last = lambda xs, key: max((jst(r.get(key)) for r in xs if r.get(key)), default=None)  # noqa: E731
    paid_no_task = sum(1 for r in vis if paid(r) > 0 and not x.tasks.get(r['visitorId']))
    still_open = sum(1 for r in rows if r['reservationStatus'] in ('RESERVED', 'IN_PROGRESS'))
    pur = raw.purchase.get(day, [])
    notes = []
    if still_open:
        notes.append(f'予約状態が「予約」「進行中」のまま {still_open}件（来院・キャンセルの入力漏れか、反映待ちの可能性）')
    if paid_no_task:
        notes.append(f'決済があるのに施術記録のない来院 {paid_no_task}件')
    if payC is not None and rec['C'] and abs(payC - rec['C']) / rec['C'] > 0.3:
        notes.append(f'決済ベースと来院ベースの差が30%超（{yen(payC - rec["C"])}）')
    lt = last(raw.tx.get(day, []), 'lastUpdatedPaymentDateTimeUtc')
    lv = last([r for r in vis], 'receptionDateTimeUtc')
    if lt and lv and lt < lv - dt.timedelta(hours=1):
        notes.append('最後の決済が最後の受付より1時間以上前（決済の反映が遅れている可能性）')
    item8 = {'予約データ': len(rows), '来院': len(vis), '決済データ': len(raw.tx.get(day, [])), '購入データ': len(pur),
             '施術データ': len(raw.proc.get(day, [])),
             'プリペイド履歴': len(raw.prepaid.get(day, [])),
             '最後の決済': lt.strftime('%H:%M') if lt else None, '最後の受付': lv.strftime('%H:%M') if lv else None,
             '決済ありで施術記録なし': paid_no_task, '状態が未確定の予約': still_open, '注意': notes}
    numbers = {'1_予想と実績の差': item1, '2_当日キャンセル': item2, '3_2施術以上の割合': item3,
               '4_メニュー未入力と決済0円': item4, '5_プリペイド購入率と再診のオプション追加率': item5,
               '6_月の進捗': item6, '7_曜日の傾向': item7, '8_データのチェック': item8}
    return {'day': day.isoformat(), 'label': f'{day.month}/{day.day}（{w}）', 'url': URL, 'numbers': numbers,
            'facts': facts(numbers, rec)}


def facts(n, rec):
    """Short factual sentences (only arithmetic on the numbers above), to help the writer."""
    f = {}
    i1 = n['1_予想と実績の差']
    top = i1['寄与額（大きい順）'][:3]
    f['1'] = [f"朝の予想 {yen(i1['朝の予想（0:00時点の予約）'])} → 着地結果 {yen(i1['着地結果（来院ベース）'])}（来院ベース、差 {i1['差（来院ベース − 朝の予想）']:+,}円）"
              + (f"、決済ベース {yen(i1['着地結果（決済ベース）'])}（差 {i1['差（決済ベース − 朝の予想）']:+,}円）" if i1['着地結果（決済ベース）'] is not None else ''),
              '寄与の大きい順: ' + '、'.join(f'{k} {v:+,}円' for k, v in top)]
    for c in i1['目立ったケース']:
        f['1'].append(f"{c['who']}: 予約「{c['予約メニュー']}」{c['予約金額']:,}円 → 実際「{c['実際の施術']}」{c['決済額']:,}円（{c['差']:+,}円）"
                      + (f"、予約になかった施術 {'・'.join(c['予約になかった施術'])}" if c['予約になかった施術'] else '')
                      + (f"、プリペイド購入 {c['プリペイド購入']:,}円" if c['プリペイド購入'] else ''))
    i2 = n['2_当日キャンセル']
    f['2'] = [f"当日キャンセル {i2['当日キャンセル']}件（来院予定 {i2['来院予定']}件の {pct(i2['当日キャンセル率'])}、{i2['判定方法']}）"]
    i3 = n['3_2施術以上の割合']
    f['3'] = [f"2施術以上 {pct(i3['2施術以上の割合'])}（当月{i3['当月内の順位'][1]}日中{i3['当月内の順位'][0]}番目、7日移動平均 {pct(i3['7日移動平均'])}、当月平均 {pct(i3['当月平均'])}）"]
    i4 = n['4_メニュー未入力と決済0円']
    f['4'] = [f"メニュー未入力 {pct(i4['メニュー未入力の割合'])}（{i4['メニュー未入力の来院']}件）、決済0円の来院 {i4['決済0円の来院']}件（うち施術あり {i4['うち施術あり（コース・プリペイド消化とみられる）']}件）"]
    i5 = n['5_プリペイド購入率と再診のオプション追加率']
    f['5'] = [f"プリペイド購入率 {pct(i5['プリペイド購入率'])}（{i5['プリペイド購入（件・金額）'][0]}件・{i5['プリペイド購入（件・金額）'][1]:,}円）、"
              f"再診のオプション追加率 {pct(i5['再診のオプション追加率'])}（{i5['うちオプション追加']}/{i5['再診（メニュー入力あり）の来院']}件）"]
    i6 = n['6_月の進捗']
    f['6'] = [f"月の実績 {yen(i6['月の実績（決済ベース、1日〜当日）'])}" + (f"、目標比 {pct(i6['目標比'])}、日割り累計比 {pct(i6['日割り累計に対して'])}" if i6['目標'] else '')
              + f"、過去{len(i6['過去の月の同じ期間'])}か月の同じ期間と比べて{i6['順位'][1]}か月中{i6['順位'][0]}番目"]
    i7 = n['7_曜日の傾向']
    f['7'] = [f"{i7['曜日']}曜: この日 {yen(i7['この日（来院ベース）'])}、当月の{i7['曜日']}曜平均 {yen(i7['当月の同じ曜日の平均（この日を除く）']) if i7['当月の同じ曜日の平均（この日を除く）'] else '—'}、"
              f"前月の{i7['曜日']}曜平均 {yen(i7['前月の同じ曜日の平均']) if i7['前月の同じ曜日の平均'] else '—'}。"
              f"平日平均／土日平均: 当月 {yen(i7['当月の平日平均']) if i7['当月の平日平均'] else '—'}／{yen(i7['当月の土日平均']) if i7['当月の土日平均'] else '—'}、"
              + (f"前月 {yen(i7['前月の平日平均'])}／{yen(i7['前月の土日平均'])}" if i7['前月の平日平均'] else '前月の日別データなし')]
    f['8'] = n['8_データのチェック']['注意'] or ['目立った欠けや遅れはありません']
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--work', default=os.environ.get('WORK', '/tmp/sales-work/landing'))
    ap.add_argument('--day', required=True, help='the closed day (JST)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--targets', default=config.TARGETS if hasattr(config, 'TARGETS') else os.path.join(os.path.dirname(HERE), 'targets.json'))
    a = ap.parse_args()
    os.umask(0o077)
    consts = page.get_consts(open(a.html, encoding='utf-8').read())
    targets = config.load_targets(a.targets) if hasattr(config, 'load_targets') else json.load(open(a.targets))
    res = analyse(Raw(a.work), consts, dt.date.fromisoformat(a.day), a.work, targets)
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(f'ANALYSIS: {a.out}')


if __name__ == '__main__':
    main()
