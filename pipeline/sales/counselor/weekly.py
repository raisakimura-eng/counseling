"""週次の「カウンセラー別の課題」ページ用の数字（前週 月〜日、比較は直前4週とクリニック全体）。

    python3 -I pipeline/sales/counselor/weekly.py --work WORK [--week-end YYYY-MM-DD] [--fetch] --out NUMBERS.json

- --week-end: 対象週の日曜（JST）。省略時は直近の終わった週（今日が月曜なら昨日まで）。
- --fetch: 対象週と直前4週を含む月の購入・予約・満足度調査を KOS から取り直す（WORK/raw）。
- 出力は患者のコメント本文を含む（課題の文章を書くための材料）。WORK はリポジトリの外に置き、コミットしない。
  ページ（review_page.py）には、Claude が書いた課題の文章と数字だけが載り、コメント本文は載らない。

数字の定義はカウンセラー販売実績ダッシュボードと同じ（aggregate.sales_block など）。
新規率は週では出さない（ダッシュボードの新規＝カルテ作成月が購入月と同じ、が週と合わないため）。
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
import aggregate as A  # noqa: E402
import fetch  # noqa: E402

BASE_WEEKS = 4
MIN_CUST = 10   # これ未満の週は「件数が少ない」と注記する


def last_week_end(today):
    return today - dt.timedelta(days=today.weekday() + 1)


def r1(x, nd=0):
    return None if x is None else round(x, nd) if nd else round(x)


def sales(rows):
    if not rows:
        return None
    b = A.sales_block(rows, None)
    return dict(customers=b['customers'], revenue=round(b['revenue']), arpu=r1(b['arpu']),
                procs_per_cust=r1(b['procs_per_cust'], 2), price_per_proc=r1(b['price_per_proc']),
                one_rate=r1(b['one_rate'], 3), prepaid_cust=b['prepaid_cust'], prepaid_amt=round(b['prepaid_amt']),
                refund_rate=r1(b['refund_rate'], 3), disc=r1(b['disc'], 3))


def by_channel(rows):
    out = {}
    for ch in ('LINE', 'GU', 'REF', 'HP'):
        s = sales([r for r in rows if r['ch'] == ch])
        if s:
            out[ch] = {k: s[k] for k in ('customers', 'arpu', 'one_rate')}
    return out


def dwell(rows, arpu):
    v = [x['dwell'] for x in rows if x['received'] and x['dwell'] and x['dwell'] > 0]
    if not v:
        return None
    med = float(statistics.median(v))
    return dict(n=len(v), med=med, per_min=r1(arpu / med) if arpu and med else None)


def voc(answers, who):
    xs = [s for a in answers for w, s in a['rat'].get('カウンセラー', []) if (w == who if who else w not in A.SHARED)]
    if not xs:
        return None
    return dict(mean=r1(sum(xs) / len(xs), 2), n=len(xs), low=sum(1 for x in xs if x <= 3))


def week_comments(answers, who):
    out = []
    for a in answers:
        cs = [s for w, s in a['rat'].get('カウンセラー', []) if w == who]
        for w, text in a['comments']:
            if w == who and text and text.strip() not in ('なし', '特になし', '없음', 'なし。', '特にありません'):
                out.append(dict(score=sum(cs) / len(cs) if cs else None, text=text.strip(), ch=a['ch']))
    return out


def numbers(work, week_end):
    w0 = week_end - dt.timedelta(days=6)
    b0 = w0 - dt.timedelta(days=7 * BASE_WEEKS)
    yms = [m for m, _, _ in fetch.months(max(A.OPEN_DAY, b0), week_end)]
    pr = A.purchase_rows(fetch.load(work, 'purchase', yms))
    sc = A.schedule_rows(fetch.load(work, 'schedule', yms))
    chart_ch = {}
    for r in sorted(fetch.load(work, 'purchase', yms), key=lambda r: r['createdDateTimeUtc']):
        if r.get('visitorChartNumber'):
            chart_ch.setdefault(r['visitorChartNumber'], A.channel(r.get('visitorFunnelName')))
    sv = A.survey_rows(fetch.load(work, 'survey', yms), chart_ch, until=week_end)
    inw = lambda d: w0 <= d <= week_end  # noqa: E731
    inb = lambda d: b0 <= d < w0  # noqa: E731
    people = {}
    for who in A.MAIN + [None]:
        mine = (lambda r: r['who'] == who) if who else (lambda r: True)
        pw = [r for r in pr if inw(r['date']) and mine(r)]
        pb = [r for r in pr if inb(r['date']) and mine(r)]
        sw = [x for x in sc if inw(x['date']) and (x['who'] == who if who else x['listed'])]
        sb = [x for x in sc if inb(x['date']) and (x['who'] == who if who else x['listed'])]
        aw = [a for a in sv if inw(a['date'])]
        ab = [a for a in sv if inb(a['date'])]
        week, base = sales(pw), sales(pb)
        if who and not week and not base:
            continue
        people[who or 'クリニック全体'] = dict(
            week=week, base=base, week_channels=by_channel(pw), base_channels=by_channel(pb),
            week_dwell=dwell(sw, week and week['arpu']), base_dwell=dwell(sb, base and base['arpu']),
            week_voc=voc(aw, who), base_voc=voc(ab, who),
            few=bool(week and week['customers'] < MIN_CUST),
            comments=week_comments(aw, who) if who else [])
    return dict(week=[w0.isoformat(), week_end.isoformat()], base=[b0.isoformat(), (w0 - dt.timedelta(days=1)).isoformat()],
                base_weeks=BASE_WEEKS, people=people)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--week-end')
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.umask(0o077)
    today = dt.datetime.now(A.JST).date()
    we = dt.date.fromisoformat(a.week_end) if a.week_end else last_week_end(today)
    if we.weekday() != 6:
        sys.exit(f'--week-end must be a Sunday: {we}')
    if a.fetch:
        fetch.fetch(a.work, max(A.OPEN_DAY, (we - dt.timedelta(days=6 + 7 * BASE_WEEKS)).replace(day=1)), we,
                    ['purchase', 'schedule', 'survey'])
    n = numbers(a.work, we)
    json.dump(n, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(f"NUMBERS: {a.out}（{n['week'][0]}〜{n['week'][1]}、{len(n['people']) - 1}名）")


if __name__ == '__main__':
    main()
