"""Load the raw KOS files written by fetch.py and index them by JST day."""
import collections
import datetime as dt
import json
import os
import re

import config

JST = dt.timezone(dt.timedelta(hours=9))
WD = '月火水木金土日'


def jst(s):
    """API timestamp (UTC, ...Z) -> aware JST datetime."""
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(JST)


def money(x):
    return (x or {}).get('value') or 0


def dlabel(d):
    return f'{d.month}/{d.day}'


def wd(d):
    return WD[d.weekday()]


def month_days(ym):
    y, m = map(int, ym.split('-'))
    d = dt.date(y, m, 1)
    out = []
    while d.month == m:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


class Raw:
    """All raw rows, indexed. Schedules by visit day, the rest by the day they happened (JST)."""

    def __init__(self, work):
        self.dir = os.path.join(work, 'raw')
        self.sched = collections.defaultdict(list)
        self.tx = collections.defaultdict(list)
        self.purchase = collections.defaultdict(list)
        self.proc = collections.defaultdict(list)
        self.prepaid = collections.defaultdict(list)
        self.fetched = {}
        seen = set()
        for f in sorted(os.listdir(self.dir)):
            m = re.match(r'(schedule|transaction|purchase|procedure|prepaid)_(\d{4}-\d{2})\.json$', f)
            if not m:
                continue
            j = json.load(open(os.path.join(self.dir, f)))
            self.fetched[(m.group(1), m.group(2))] = j.get('fetchedAt')
            for r in j['data']:
                kind = m.group(1)
                if kind == 'schedule':
                    if r['scheduleId'] in seen:
                        continue
                    seen.add(r['scheduleId'])
                    self.sched[jst(r['reservationStartDateTimeUtc']).date()].append(r)
                elif kind == 'transaction':
                    self.tx[dt.date.fromisoformat(r['_day'])].append(r)
                elif kind == 'purchase':
                    self.purchase[jst(r['createdDateTimeUtc']).date()].append(r)
                elif kind == 'procedure':
                    self.proc[jst(r['completedDateTimeUtc']).date()].append(r)
                else:
                    self.prepaid[jst(r['chargedDateTimeUtc']).date()].append(r)
        vf = os.path.join(self.dir, 'visitors.json')
        self.visitors = json.load(open(vf)) if os.path.exists(vf) else {}

    def fetched_at(self, kind, d):
        return self.fetched.get((kind, d.strftime('%Y-%m')))

    # --- per-row helpers -------------------------------------------------
    def age_band(self, visitor_id, on):
        dob = (self.visitors.get(visitor_id) or {}).get('dateOfBirth')
        if not dob:
            return None
        age = on.year - int(dob[:4])  # 年代 = visit year − birth year (birthday not considered), as on the page
        if age < 10:
            return None
        return f'{min(age // 10, 7) * 10}代'


def excluded(r):
    """'staff' / 'influencer' / None for a schedule row (see config.EXCLUDE_*)."""
    for c in r.get('visitorCategoryNames') or []:
        if c in config.EXCLUDE_CATEGORIES:
            return config.EXCLUDE_CATEGORIES[c]
    if config.EXCLUDE_VISITOR_MEMO and config.EXCLUDE_VISITOR_MEMO.search(r.get('visitorMemo') or ''):
        return 'influencer'
    return None


def vtype(r):
    return '初診' if r.get('isFirstProcedureSchedule') else '再診'


def resv(r):
    """予約金額 (希望施術メニュー総額)."""
    return money(r.get('requestedProductOptionTotalPriceV2'))


def paid(r):
    """来院時の施術決済総額 (= the visit-based 着地結果 per visit)."""
    return money(r.get('optionItemTotalPriceV2'))


def start(r):
    return jst(r['reservationStartDateTimeUtc'])


def reserved_at(r):
    return jst(r.get('reservedDateTimeUtc'))


def menu_label(r, width=40):
    """Requested menus as the page shows them: price tags 【…価格】 and 指名料 removed, joined with ＋."""
    out = []
    for t in r.get('requestedOptionTitles') or []:
        if t.startswith('指名料'):
            continue
        t = re.sub(r'【[^】]*価格】', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        if t.startswith('しわボトックス 韓国製'):
            t = 'しわボトックス'
        out.append(t)
    s = ' ＋ '.join(out) or 'メニュー未入力'
    return s if len(s) <= width else s[:width - 1] + '…'
