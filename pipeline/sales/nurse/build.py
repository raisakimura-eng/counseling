"""公開中の看護師ダッシュボードを、KOS OpenAPI のデータで作り直す。

    python3 -I pipeline/sales/nurse/build.py --html CURRENT.html --work WORK --out NEW.html
        [--until YYYY-MM-DD] [--from YYYY-MM-DD] [--fetch] [--accept-closed-month-changes] [--strict-new-staff]

- --html: 今の公開ページ（netlify.download('naa-nurse', ...) で保存したもの）。
- --work: API の生データを置く作業フォルダ（リポジトリの外。WORK/raw/ に月ごと）。
- --until: 反映する最終日（JST）。省略時は前日。
- --from: 期間の初日。省略時は --until の月の1日（＝当月の1日〜前日。毎月1日の更新では前月まるごと）。
  その期間に施術データがまだ1件も無いとき（月初が休診日など）は、前月の1日からにする（ページは
  施術の無い期間を表示できないため）。
- --fetch: 期間の月を API から取り直す（--fetch-all も同じ）。付けなければ手元の WORK/raw だけで作る。
- 書き換えるのは `const EMBED = {...};` の1行と、設定の定数 DOCTORS・ALIAS・MENTION（CSS / ほかの JS には触れない）。
  定数は「今のページの値 + PAGE_ADD + staff_roles.csv でダッシュボード職種が医師の人（DOCTORS）」。足すだけで消さない。
  ページに日付の入った固定の文は無い（期間や未取込の日は JS が EMBED から表示する）。

止まる条件（何も書き出さない）:
- --until が今のページの最終日より前
- 今のページと重なる日のうち --until の2日前までの日で、看護師の施術件数の合計が max(2件, 2%) を超えて、
  または指名件数が2件を超えてずれる（あとからの修正にしては大きい。verify.py で確認する）
- 今のページがまだ Excel 版（EMBED.files が .xlsx）: 初回の切り替えだけ --accept-closed-month-changes で通す
  （購入の欠損日の補完・あとからの担当の修正で数字が変わる）。API 版のページに付けると止まる。
警告（止めない。--strict-new-staff で止める）: README「人の判断が要るもの」
- 施術者・満足度調査の施術者に、DOCTORS / NON_STAFF に無い医師（staff_roles.csv で医師）→ 看護師として表示されてしまう
- staff_roles.csv で看護師でも医師でもない名前、csv に無い名前（表記ゆれ・逆順の名前なら ALIAS）
- 指名料「看護師_○○」が期間の看護師の誰にも当たらない（ALIAS が要る）
- 今のページにも MENTION にも無い看護師（MENTION の短い呼び名・ALIAS を足すか）
"""
import argparse
import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregate as A  # noqa: E402
import fetch  # noqa: E402
import page  # noqa: E402
import verify  # noqa: E402

JST = A.JST
STAFF_CSV = os.path.join(HERE, '..', '..', '..', 'data', 'staff_roles.csv')


def month_start(d):
    return d.replace(day=1)


def prev_month(d):
    return (d.replace(day=1) - dt.timedelta(days=1)).replace(day=1)


def has_treatment(e):
    return any(r[0] is None and r[2] is not None for r in e['T'])


def is_excel(e):
    return any(str(f).endswith(('.xlsx', '.xls')) for f in e.get('files') or [])


def drift(old_v, new_v, settled):
    """settled（日付文字列の集合）の日で、施術件数の合計・指名件数が大きくずれた日。"""
    out = []
    for day in sorted(settled):
        a, b = old_v.get((day, 'same')), new_v.get((day, 'same'))
        if not a or not b:
            continue
        ta, tb = a[0], b[0]
        if abs(tb['cnt'] - ta['cnt']) > max(2, 0.02 * ta['cnt']):
            out.append(f"{day}: 施術件数 {ta['cnt']} -> {tb['cnt']}")
        if ta['nom'] is not None and tb['nom'] is not None and abs(tb['nom'] - ta['nom']) > 2:
            out.append(f"{day}: 指名件数 {ta['nom']} -> {tb['nom']}")
    return out


# ページの JS 定数に毎回足す設定（既にあるものは残す。2026-10-12 オーナー決定）。
# DOCTORS には data/staff_roles.csv のダッシュボード職種「医師」も自動で足す（csv は他のダッシュボードと共有。ここからは変えない）。
PAGE_ADD = {
    'DOCTORS': ['渡辺一惠'],                                   # 退職した医師（csv でも医師）。看護師に含めない
    'ALIAS': {'吉澤沙也加': '神田令', '吉澤': '神田令'},        # 同じ人。表示は神田令にまとめる
    'MENTION': {'阿部彩乃': ['阿部'], '神田令': ['吉澤']},      # 輝き言及の短い呼び名
}


def merged_config(cfg):
    """ページの定数 + PAGE_ADD + staff_roles.csv の医師（ダッシュボード職種「医師」）。既にあるものは消さない。"""
    add = PAGE_ADD
    csv_doctors = [page.norm(r['氏名']) for r in csv.DictReader(open(STAFF_CSV, encoding='utf-8'))
                   if r['ダッシュボード職種'] == '医師']
    out = dict(cfg)
    out['DOCTORS'] = list(dict.fromkeys(cfg['DOCTORS'] + [page.norm(n) for n in add.get('DOCTORS', [])] + csv_doctors))
    out['ALIAS'] = {**cfg['ALIAS'], **add.get('ALIAS', {})}
    mention = {k: list(v) for k, v in cfg['MENTION'].items()}
    for k, v in add.get('MENTION', {}).items():
        mention[k] = list(dict.fromkeys(mention.get(k, []) + v))
    out['MENTION'] = mention
    return out


def staff_check(e, cfg, old_names):
    """人の判断が要る名前（警告の文のリスト）。"""
    calc = page.Calc(cfg)
    roles = {page.norm(r['氏名']): r['ダッシュボード職種'] for r in csv.DictReader(open(STAFF_CSV, encoding='utf-8'))}
    for k, v in cfg['ALIAS'].items():
        roles.setdefault(v, roles.get(k, ''))
    seen = {}
    path = []
    for r in e['T']:
        if isinstance(r[0], str) and '->' in r[0]:
            path = [s.strip() for s in r[0].split('->')[1:]]
        elif r[2] is not None and len(path) >= 2:
            for n in path[0].split(','):
                seen.setdefault(calc.canon(n), [0, 0])[0] += 1
    for r in e['S']:
        if r[2] == '施術者' and r[4] == '数値入力式':
            seen.setdefault(calc.canon(r[3]), [0, 0])[1] += 1
    known = set(old_names) | set(cfg['MENTION']) | set(cfg['ALIAS'].values())
    warn = []
    for n, (t, s) in sorted(seen.items()):
        if not n or calc.is_doctor(n) or calc.is_non_staff(n):
            continue
        role = roles.get(n)
        what = f'{n}（施術 {t}件・施術の評価 {s}件）'
        if role == '医師':
            warn.append(f'医師なのに DOCTORS に無い → 看護師として表示される: {what}')
        elif role is None:
            warn.append(f'staff_roles.csv に無い名前（新しい人？表記ゆれなら ALIAS）: {what}')
        elif role != '看護師':
            warn.append(f'staff_roles.csv で {role or "職種なし"} の人が施術者になっている（NON_STAFF に足す？）: {what}')
        elif t and n not in known:
            warn.append(f'新しい看護師（今のページにも MENTION にも無い。MENTION の短い呼び名・逆順の名前なら ALIAS を足すか）: {what}')
    nurses = {n for n, (t, _) in seen.items() if t and not calc.is_doctor(n) and not calc.is_non_staff(n)}
    for r in e['P']:
        fee = r[2]
        if r[3] == '指名料' and page.norm(fee).startswith('看護師'):
            c = calc.canon(page.norm(fee)[len('看護師_'):] if page.norm(fee).startswith('看護師_') else page.norm(fee))
            if c not in nurses and not any(n.startswith(c) or n.endswith(c) for n in nurses):
                warn.append(f'指名料「{fee}」が期間の看護師の誰にも当たらない（ALIAS を足すか）')
    return list(dict.fromkeys(warn))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--until')
    ap.add_argument('--from', dest='d0')
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--fetch-all', action='store_true', help='same as --fetch (the whole period is re-fetched)')
    ap.add_argument('--accept-closed-month-changes', action='store_true',
                    help='初回の切り替え専用: Excel 版から API 版にするときの数字の変化を受け入れる（日次では使わない）')
    ap.add_argument('--strict-new-staff', action='store_true')
    a = ap.parse_args()
    os.umask(0o077)

    until = dt.date.fromisoformat(a.until) if a.until else dt.datetime.now(JST).date() - dt.timedelta(days=1)
    d0 = dt.date.fromisoformat(a.d0) if a.d0 else month_start(until)
    html = page.read_html(a.html)
    old_cfg = page.config(html)
    cfg = merged_config(old_cfg)
    old = page.get_embed(html)
    o0, o1 = verify.page_period(old)
    if until < o1:
        sys.exit(f"STOP: --until {until} is before the page's last date {o1}")

    excel_page = is_excel(old)
    if a.accept_closed_month_changes and not excel_page:
        sys.exit('STOP: --accept-closed-month-changes is only for the first switch from the Excel-export page; '
                 'this page is already built from the API')
    if excel_page and not a.accept_closed_month_changes:
        sys.exit('STOP: the live page is still the Excel-export version. For the first API build pass '
                 '--accept-closed-month-changes (gap days filled, later edits in KOS)')

    get = a.fetch or a.fetch_all
    if get:
        fetch.fetch(a.work, d0, until)
    new = verify.rebuild(a.work, d0, until)
    if not has_treatment(new) and not a.d0:
        d0 = prev_month(until)
        print(f'info: no treatment data in {month_start(until)}..{until} yet; showing from {d0}')
        if get:
            fetch.fetch(a.work, d0, until)
        new = verify.rebuild(a.work, d0, until)
    if not has_treatment(new):
        sys.exit(f'STOP: no treatment data in {d0}..{until} (the page cannot show an empty period)')

    old_v, new_v = page.views(old, old_cfg), page.views(new, cfg)
    if cfg != old_cfg:
        for k in ('DOCTORS', 'ALIAS', 'MENTION'):
            if cfg[k] != old_cfg[k]:
                print(f'page constant {k} updated (build.PAGE_ADD / staff_roles.csv)')
    settled = {d for (d, _) in old_v if d != 'ALL' and d <= (until - dt.timedelta(days=2)).isoformat()
               and d >= d0.isoformat()}
    dr = drift(page.views(old, cfg) if cfg != old_cfg else old_v, new_v, settled)   # データの変化だけを見る（設定は同じにそろえる）
    if dr and not a.accept_closed_month_changes:
        sys.exit('STOP: settled days differ from the live page more than later edits would explain '
                 '(check with verify.py --table):\n  ' + '\n  '.join(dr))
    for m in dr:
        print('settled day changed:', m)
    if excel_page:
        for key, n, k, x, y in verify.compare(old_v, {k: v for k, v in new_v.items() if k in old_v}):
            if key == ('ALL', 'same') and n == '*' and k in ('cnt', 'pts', 'nom', 'voc_n'):
                print(f'first switch: 全期間 {k}: {x} -> {y}')

    old_names = set(old_v.get(('ALL', 'same'), ({}, {}))[1])
    warn = staff_check(new, cfg, old_names)
    for w in warn:
        print('WARNING:', w)
    if warn and a.strict_new_staff:
        sys.exit('STOP: names that need a human decision (see WARNING lines; README「人の判断が要るもの」)')

    out = page.set_config(page.set_embed(html, new), cfg)
    with open(a.out, 'w', encoding='utf-8') as fh:
        fh.write(out)
    t = new_v[('ALL', 'same')][0]
    print(f"built {a.out}: {d0}..{until}; 施術 {len(new['T'])} rows, 購入 {len(new['P'])} rows, 満足度 {len(new['S'])} rows; "
          f"看護師 {t['nurses']}名, 施術件数 {t['cnt']}, 施術患者数 {t['pts']}, 指名 {t['nom']}, VOC {t['voc']}(n={t['voc_n']})")


if __name__ == '__main__':
    main()
