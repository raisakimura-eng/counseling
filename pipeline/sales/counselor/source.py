"""作業フォルダの API 生データを読み、aggregate.build に渡す行をそろえる。

export_gaps=True にすると、公開版の元になった Excel エクスポートの欠損（README「既知の欠損」）を
わざと再現する。締めた月の照合（verify.py）でだけ使い、毎日の更新では使わない。
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregate as A  # noqa: E402
import fetch  # noqa: E402

JST = A.JST
# 公開版（2026-10-10 エクスポート）の欠損
EXPORT_SALES_GAPS = [(dt.datetime(2026, 9, 24, 10, 16, tzinfo=JST), dt.datetime(2026, 9, 25, tzinfo=JST))]
EXPORT_VISIT_GAPS = {dt.date(2026, 9, 29), dt.date(2026, 10, 1), dt.date(2026, 10, 2)}
# 満足度調査も 9/24 提出分（15件）が公開版に入っていない（ページには「欠損なく反映」とあるが、照合で判明）
EXPORT_SURVEY_GAPS = [(dt.datetime(2026, 9, 24, tzinfo=JST), dt.datetime(2026, 9, 25, tzinfo=JST))]


def month_keys(d0, d1):
    return [m for m, _, _ in fetch.months(d0, d1)]


def load(work, last_date, voc_last=None, visit_last=None, export_gaps=False, exclude_shared_voc=True, main=A.MAIN):
    yms = month_keys(A.OPEN_DAY, last_date)
    pr = A.purchase_rows(fetch.load(work, 'purchase', yms), EXPORT_SALES_GAPS if export_gaps else ())
    sc = A.schedule_rows(fetch.load(work, 'schedule', yms), EXPORT_VISIT_GAPS if export_gaps else (),
                         fallback=A.purchase_attribution(A.purchase_rows(fetch.load(work, 'purchase', yms))))
    raw_p = fetch.load(work, 'purchase', yms)
    # 回答者のチャネル: カルテ番号 → 最初の購入の患者流入チャネル（購入が無ければ OTHER）
    chart_ch = {}
    for r in sorted(raw_p, key=lambda r: r['createdDateTimeUtc']):
        if r.get('visitorChartNumber'):
            chart_ch.setdefault(r['visitorChartNumber'], A.channel(r.get('visitorFunnelName')))
    sv = A.survey_rows(fetch.load(work, 'survey', yms), chart_ch, until=voc_last or last_date,
                       skip=EXPORT_SURVEY_GAPS if export_gaps else ())
    return A.build(pr, sc, sv, last_date, voc_last=voc_last, visit_last=visit_last, main=main,
                   exclude_shared_voc=exclude_shared_voc)


def latest_dates(work, until):
    """データ源ごとの最終日（その日までデータがある日）。"""
    yms = month_keys(A.OPEN_DAY, until)
    last = lambda rows, key: max((A.jdt(r[key]).date() for r in rows if A.jdt(r[key]).date() <= until), default=None)  # noqa: E731
    return dict(sales=last(fetch.load(work, 'purchase', yms), 'createdDateTimeUtc'),
                visit=last([x for x in fetch.load(work, 'schedule', yms) if x.get('receptionDateTimeUtc')], 'reservationStartDateTimeUtc'),
                voc=last(fetch.load(work, 'survey', yms), 'submittedDateTimeUtc'))
