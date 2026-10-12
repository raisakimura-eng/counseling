"""公開中のカウンセラー販売実績ダッシュボードを、KOS OpenAPI のデータで作り直す。

    python3 -I pipeline/sales/counselor/build.py --html CURRENT.html --work WORK --out NEW.html
        [--until YYYY-MM-DD] [--fetch | --fetch-all] [--accept-closed-month-changes]

- --html: 現在の公開ページ（Netlify の naa-counselor から netlify.download で保存したもの、または Artifact read の保存ファイル）。
- --work: API の生データを置く作業フォルダ（リポジトリの外。fetch.py が WORK/raw/ に月ごとに保存）。
- --until: 反映する最終日（JST）。省略時は前日。
- --fetch: 足りない月を取得し、--until の月と前月は取り直す（返金・担当の修正が前月にも入るため）。
  --fetch-all: 全月を取り直す（週1回など）。どちらも付けなければ、手元の WORK/raw だけで作る。
- 書き換えるのは `const D = {...};` の1行と、本文中の日付つきの文（集計期間・進行時間の反映日・
  データの欠損・データ源ごとの締め・VOCの回答日・フッターの出典）だけ。CSS / JS には触れない。

止まる条件（何も書き出さない）:
- 新しい D の最終日が、今のページより前になる
- 締めた月（--until の前月より前の月）のクリニック全体の顧客数が1%超、売上が2%超、今のページとずれる
  （Excel 版から API 版への初回切り替えだけ --accept-closed-month-changes で通す。日次では使わない）
警告（止めない。--strict-new-staff を付けると止める）:
- 表示していないカウンセラー（staff_roles.csv でカウンセラー、または csv に無い名前）が当月5人以上を担当している
  → 新しいカウンセラーなら aggregate.MAIN と本文「表示するカウンセラー」の文に足す（人の判断）
"""
import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregate as A  # noqa: E402
import fetch  # noqa: E402
import page  # noqa: E402
import source  # noqa: E402

JST = A.JST


EXCEL_FOOTER = 'エクスポート）'   # Excel 版のフッター「…（2026年3月20日〜10月10日エクスポート）」


def prev_month(d):
    return (d.replace(day=1) - dt.timedelta(days=1)).replace(day=1)


def do_fetch(work, until, everything):
    names = ['purchase', 'schedule', 'survey']
    if everything:
        fetch.fetch(work, A.OPEN_DAY, until, names)
        return
    fetch.fetch(work, A.OPEN_DAY, until, names, skip_existing=True)          # 足りない月
    fetch.fetch(work, max(A.OPEN_DAY, prev_month(until)), until, names)      # 前月と当月は取り直す


def closed_drift(old, new, until):
    """締めた月（前月より前）のクリニック全体の顧客数・売上のずれ。"""
    limit = prev_month(until).strftime('%Y-%m')
    out = []
    for m in old['months']:
        if m >= limit:
            continue
        a, b = old['clinic']['ALL'].get(m), new['clinic']['ALL'].get(m)
        if not a or not b:
            out.append(f'{m}: missing')
            continue
        dc = abs(b['customers'] - a['customers']) / max(a['customers'], 1)
        dr = abs(b['revenue'] - a['revenue']) / max(a['revenue'], 1)
        if dc > 0.01 or dr > 0.02:
            out.append(f"{m}: customers {a['customers']} -> {b['customers']}, revenue {a['revenue']:,.0f} -> {b['revenue']:,.0f}")
    return out


def staff_check(work, until, main):
    """当月の会計担当のうち、表示していないカウンセラー（staff_roles.csv でカウンセラー、または csv に無い名前）が
    5人以上を担当していればその名前と人数、あわせて共用アカウント名義の顧客数を返す。"""
    import csv
    roles = {r['氏名']: r['ダッシュボード職種'] for r in csv.DictReader(open(A.STAFF_CSV, encoding='utf-8'))}
    rows = A.purchase_rows(fetch.load(work, 'purchase', [until.strftime('%Y-%m')]))
    cnt = {}
    for r in rows:
        if r['who'] and r['who'] not in main:
            cnt.setdefault(r['who'], set()).add(r['pid'])
    extra = {n: len(v) for n, v in cnt.items()
             if n not in A.SHARED and roles.get(n, 'カウンセラー') == 'カウンセラー' and len(v) >= 5}
    shared = {n: len(v) for n, v in cnt.items() if n in A.SHARED}
    return extra, shared, len({r['pid'] for r in rows})


def notes(sales_last, voc_last, visit_last):
    jp = page.jp
    gap = ('全期間をKOS OpenAPIから直接集計しており、欠損日はありません。以前のExcelエクスポート版で欠けていた'
           '9月24日10時15分以降の販売、9月24日の満足度調査、9月29日・10月1〜2日の来院も含みます。'
           'あとから処理された返金や担当の修正も反映するため、締めた月の数字が以前の版と少し異なります。'
           '5月28日以前は予約データにカウンセラー名が入っていないことが多く、進行時間の担当は同じ日の会計担当で補っています。')
    if len({sales_last, voc_last, visit_last}) == 1:
        close = f'販売・売上、来院・進行時間、満足度調査とも{jp(sales_last)}まで（毎日、前日分までを反映）。'
    else:
        close = (f'販売・売上は{jp(sales_last)}まで、来院・進行時間は{jp(visit_last)}まで、'
                 f'満足度調査は{jp(voc_last)}まで（毎日、前日分までを反映）。')
    return dict(gap=gap, close=close)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--until')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--fetch', action='store_true')
    g.add_argument('--fetch-all', action='store_true')
    ap.add_argument('--accept-closed-month-changes', action='store_true',
                    help='初回の切り替え専用: 締めた月の数字の変化を受け入れる（日次では使わない）')
    ap.add_argument('--strict-new-staff', action='store_true')
    a = ap.parse_args()
    os.umask(0o077)

    until = dt.date.fromisoformat(a.until) if a.until else dt.datetime.now(JST).date() - dt.timedelta(days=1)
    if a.fetch or a.fetch_all:
        do_fetch(a.work, until, a.fetch_all)

    html = page.read_html(a.html)
    old = page.get_d(html)
    if until < dt.date.fromisoformat(old['last_date']):
        sys.exit(f"STOP: --until {until} is before the page's last date {old['last_date']}")

    last = source.latest_dates(a.work, until)
    sales_last = until                                   # 売上0の日（休診日）でも期間は until まで
    visit_last = last['visit'] or until
    voc_last = last['voc'] or until
    main_list = list(dict.fromkeys(list(A.MAIN) + [n for n in old.get('main', []) if n not in A.MAIN]))
    new = source.load(a.work, sales_last, voc_last=voc_last, visit_last=visit_last, main=main_list)

    excel_page = EXCEL_FOOTER in html
    if a.accept_closed_month_changes and not excel_page:
        sys.exit('STOP: --accept-closed-month-changes is only for the first switch from the Excel-export page; '
                 'this page is already built from the API')
    if excel_page and not a.accept_closed_month_changes:
        sys.exit('STOP: the live page is still the Excel-export version. For the first API build pass '
                 '--accept-closed-month-changes (closed months change: gap fill, later refunds, shared-account VOC exclusion)')
    drift = closed_drift(old, new, until)
    if drift and not a.accept_closed_month_changes:
        sys.exit('STOP: closed months differ from the live page (check with verify.py; '
                 'pass --accept-closed-month-changes only for the first switch):\n  ' + '\n  '.join(drift))
    for m in drift:
        print('closed month changed:', m)
    extra, shared, total = staff_check(a.work, until, main_list)
    if extra:
        msg = ('counselor(s) not on the dashboard with >=5 customers this month (add to aggregate.MAIN and the page text?): '
               + ', '.join(f'{n} {c}人' for n, c in extra.items()))
        if a.strict_new_staff:
            sys.exit('STOP: ' + msg)
        print('WARNING:', msg)
    if shared:
        print('info: customers billed under shared accounts this month (only in クリニック全体): '
              + ', '.join(f'{n} {c}人' for n, c in shared.items()) + f' / {total}人')

    out = page.set_d(html, new)
    out = page.set_dates(out, sales_last, voc_last, visit_last, visit_last, notes(sales_last, voc_last, visit_last),
                         shared=sorted(A.SHARED))
    with open(a.out, 'w', encoding='utf-8') as fh:
        fh.write(out)
    c = new['clinic']['ALL']
    cur = new['months'][-1]
    print(f"built {a.out}: sales to {sales_last}, visits to {visit_last}, survey to {voc_last}; "
          f"{cur}: customers {c[cur]['customers']}, revenue {c[cur]['revenue']:,.0f}; "
          f"ALL: customers {c['ALL']['customers']} (unique {c['ALL']['unique_customers']}), revenue {c['ALL']['revenue']:,.0f}")


if __name__ == '__main__':
    main()
