"""看護師ダッシュボードの HTML から `const EMBED = {...};` を読み書きし、ページの集計（JS の compute / build）を
Python でそのまま再現する（verify.py・build.py の照合用）。

画面は EMBED（施術・購入・満足度調査の行）とページ内の設定 DOCTORS・NON_STAFF・ALIAS・MENTION から
JS で描画される。build.py は EMBED の行だけを差し替え、CSS / JS / 設定には触れない。
compute() / board() は JS の compute() / build() / render() の数値部分を1行ずつ移したもの。
JS を変えたらここも合わせる（check_render.js が Chromium の表示とこの再現を突き合わせる）。
"""
import decimal
import math
import json
import re

EMBED_LINE = re.compile(r'^const EMBED = (\{.*\});[ \t]*$', re.M)
WRAP_HEAD = re.compile(r'^<!doctype html><html><head><meta charset=utf8>.*?</head><body>', re.S | re.I)
DATE_RE = re.compile(r'^\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}$')
TRIVIAL = re.compile(r'^(なし|特になし|無し|ない|없음\.?|특별히 없음|-|ー|特にありません|とくになし)$')


def read_html(path):
    t = open(path, encoding='utf-8').read()
    m = WRAP_HEAD.match(t)
    if m and '<title>NaA 看護師' not in t[:m.end()]:
        t = t[m.end():]
        t = t[:t.rindex('</body></html>')] if t.rstrip().endswith('</body></html>') else t
    return t


def get_embed(html):
    m = EMBED_LINE.search(html)
    if not m:
        raise ValueError('const EMBED = {...}; not found')
    return json.loads(m.group(1))


def set_embed(html, e):
    js = json.dumps(e, ensure_ascii=False).replace('</', '<\\/')
    out, n = EMBED_LINE.subn(lambda _: 'const EMBED = ' + js + ';', html, count=1)
    if n != 1:
        raise ValueError('const EMBED = {...}; not found')
    return out


def _js_literal(html, name, close):
    m = re.search(r'^const ' + name + r' = (.*?' + re.escape(close) + r');', html, re.M | re.S)
    if not m:
        raise ValueError(f'const {name} not found')
    body = re.sub(r'//[^\n]*', '', m.group(1))
    body = re.sub(r"'((?:[^'\\]|\\.)*)'", lambda x: json.dumps(x.group(1), ensure_ascii=False), body)
    body = re.sub(r',\s*([}\]])', r'\1', body)
    return json.loads(body)


def config(html):
    """ページ内の設定（医師・非個人名・表記ゆれ・輝き言及の追加語）。"""
    return dict(DOCTORS=_js_literal(html, 'DOCTORS', ']'), NON_STAFF=_js_literal(html, 'NON_STAFF', ']'),
                ALIAS=_js_literal(html, 'ALIAS', '}'), MENTION=_js_literal(html, 'MENTION', '}'))


def _js(v):
    return json.dumps(v, ensure_ascii=False, separators=(',', ':')).replace('"', "'")


def set_config(html, cfg):
    """DOCTORS・ALIAS・MENTION の定数の行を cfg の内容で書き直す（ほかの JS には触れない）。"""
    subs = [(r"^const DOCTORS = \[.*?\];", 'const DOCTORS = ' + _js(cfg['DOCTORS']) + ';'),
            (r"^const ALIAS = \{.*?\};", 'const ALIAS = ' + _js(cfg['ALIAS']) + ';'),
            (r"^const MENTION = \{.*?\n\};", 'const MENTION = { // extra tokens for 輝きスタッフ\n  '
             + ','.join(f'{_js(k)}:{_js(v)}' for k, v in cfg['MENTION'].items()) + '\n};')]
    for pat, rep in subs:
        html, n = re.subn(pat, lambda _: rep, html, count=1, flags=re.M | re.S)
        if n != 1:
            raise ValueError(f'constant not found: {pat[:20]}')
    return html


# ------------------------------------------------------------- JS の compute / build の再現

def norm(s):
    return '' if s is None else re.sub(r'[\s　﻿]', '', str(s))


def dstr(v):
    if v is None:
        return None
    m = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', str(v))
    return f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}' if m else None


class Calc:
    def __init__(self, cfg):
        self.cfg = cfg
        self.non_staff = {norm(x) for x in cfg['NON_STAFF']}

    def canon(self, s):
        n = norm(s)
        return self.cfg['ALIAS'].get(n) or n

    def is_doctor(self, n):
        return n in self.cfg['DOCTORS']

    def is_non_staff(self, n):
        return not n or n in self.non_staff

    def compute(self, D, day=None):
        path, leaves = [], []
        for r in D['T']:
            g, cat, item, tanto, couns = r[:5]
            dur = r[5] if len(r) > 5 and isinstance(r[5], (int, float)) and not isinstance(r[5], bool) else None
            if isinstance(g, str) and '->' in g:
                path = [s.strip() for s in g.split('->')[1:]]
                continue
            if cat is None and item is None and tanto is None and couns is None:
                continue
            di = next((i for i, s in enumerate(path) if DATE_RE.match(s)), -1)
            if di < 1:
                continue
            leaves.append(dict(perf=[x for x in map(self.canon, (path[di - 1] or '').split(',')) if x],
                               date=dstr(path[di]), pt=norm(path[di + 1] if di + 1 < len(path) else None),
                               cat=cat, item=item, tanto=self.canon(tanto), dur=dur))
        proc = [l for l in leaves if l['item'] is not None]
        dates = sorted({l['date'] for l in proc if l['date']})
        is_m = bool(day) and len(day) == 7   # 'YYYY-MM' = 月の表示

        def in_sel(d):
            return not day or ((d or '').startswith(day) if is_m else d == day)
        if day:
            proc = [l for l in proc if in_sel(l['date'])]
        roster = {}

        def get(n):
            if n not in roster:
                roster[n] = dict(name=n, cnt=0, visits=set(), assist=0, days={}, cats={}, nomFix=0, nomEst=0, inTreat=False,
                                 durs=[])
            return roster[n]
        for l in proc:
            for n in [p for p in l['perf'] if not self.is_doctor(p) and not self.is_non_staff(p)]:
                o = get(n)
                o['inTreat'] = True
                o['cnt'] += 1
                o['visits'].add(l['date'] + '|' + l['pt'])
                o['days'][l['date']] = o['days'].get(l['date'], 0) + 1
                c = (l['cat'] or '未分類').split(',')[-1]
                o['cats'][c] = o['cats'].get(c, 0) + 1
                if l['dur'] is not None:
                    o['durs'].append(l['dur'])
        for l in proc:
            if l['tanto'] and l['tanto'] not in l['perf'] and any(map(self.is_doctor, l['perf'])) and l['tanto'] in roster:
                roster[l['tanto']]['assist'] += 1
        nurse_set = list(roster)

        def resolve_fee(s):
            c = self.canon(re.sub(r'^看護師_', '', norm(s)))
            if c in nurse_set:
                return c
            return next((n for n in nurse_set if n.startswith(c) or n.endswith(c)), c)
        visits = {}
        for dt_, p_, fee, fee_cat, cls, status in D['P']:
            d, p = dstr(dt_), norm(p_)
            v = visits.setdefault(d + '|' + p if d else 'null|' + p, dict(d=d, p=p, cls=cls or '', fees=[]))
            if cls:
                v['cls'] = cls
            if fee_cat == '指名料' and norm(fee).startswith('看護師') and status != '返金済み':
                v['fees'].append(resolve_fee(fee))
        est_unassigned = 0
        for v in visits.values():
            if day and not in_sel(v['d']):
                continue
            for n in v['fees']:
                get(n)['nomFix'] += 1
            if not v['fees'] and '看護師指名あり' in v['cls']:
                ls = [l for l in proc if l['date'] == v['d'] and l['pt'] == v['p']]
                cands = list(dict.fromkeys(n for l in ls for n in l['perf'] if n in nurse_set))
                if not cands:
                    cands = list(dict.fromkeys(l['tanto'] for l in ls if l['tanto'] in nurse_set))
                if cands:
                    for n in cands:
                        get(n)['nomEst'] += 1
                else:
                    est_unassigned += 1
        sel = [d for d in dates if in_sel(d)]
        p0 = (sel[0] if sel else None) if is_m else day or (dates[0] if dates else None)
        p1 = (sel[-1] if sel else None) if is_m else day or (dates[-1] if dates else None)
        resp, shine = {}, []
        for rd, _pt, typ, target, qtype, title, score, val, rid in D['S']:
            d = dstr(rd)
            if title and '輝いて' in str(title) and val:
                shine.append(dict(d=d, txt=str(val)))
            if typ != '施術者':
                continue
            n = self.canon(target)
            if not n or self.is_doctor(n) or self.is_non_staff(n):
                continue
            k = f'{rid}|{n}'
            resp.setdefault(k, dict(n=n, d=d))
            if qtype == '数値入力式' and score is not None:
                resp[k]['score'] = float(score)
            elif qtype != '数値入力式':
                resp[k]['text'] = val
        resp_list = [x for x in resp.values() if x.get('score') is not None or x.get('text')]
        return dict(proc=proc, dates=dates, roster=roster, resp=resp_list, shine=shine, p0=p0, p1=p1, day=day,
                    isM=is_m, ndays=len(sel) if is_m else None,
                    est_unassigned=est_unassigned, pDates={v['d'] for v in visits.values()},
                    sDates={dstr(r[0]) for r in D['S']})

    def board(self, C, voc_mode='same'):
        """JS の build(): 看護師ごとの行（スコアボード・散布図・ヒートマップ・VOC の元）。"""
        def in_p(d):
            return voc_mode == 'all' or (d and C['p0'] and C['p0'] <= d <= C['p1'])
        vocs = [r for r in C['resp'] if in_p(r['d'])]
        names = list(dict.fromkeys(list(C['roster']) + [r['n'] for r in vocs]))
        rows = []
        for n in names:
            o = C['roster'].get(n) or dict(cnt=0, visits=set(), assist=0, days={}, cats={}, nomFix=0, nomEst=0, inTreat=False,
                                           durs=[])
            mine = [v for v in vocs if v['n'] == n]
            sc = [v['score'] for v in mine if v.get('score') is not None]
            avg = sum(sc) / len(sc) if sc else None
            st = 'na'
            if sc:
                st = 'good'
                if avg < 4.5 or min(sc) <= 3:
                    st = 'warn'
                if avg < 4.0 or min(sc) <= 2:
                    st = 'crit'
            toks = [n] + self.cfg['MENTION'].get(n, [])
            ment = sum(1 for s in C['shine'] if in_p(s['d']) and any(t in norm(s['txt']) for t in toks))
            comments = [v for v in mine if v.get('text') and not TRIVIAL.match(re.sub(r'[。．.！!、]+$', '', norm(v['text'])))]
            nv, nom = len(o['visits']), o['nomFix'] + o['nomEst']
            rows.append(dict(name=n, cnt=o['cnt'], pts=nv, assist=o['assist'], days=dict(o['days']), cats=dict(o['cats']),
                             nomFix=o['nomFix'], nomEst=o['nomEst'], nom=nom, rate=nom / nv if nv else None, avg=avg,
                             n=len(sc), low=sum(1 for s in sc if s <= 3), st=st, ment=ment,
                             comments=sorted([(v.get('score'), v['d'] or '', str(v['text'])) for v in comments], key=str),
                             inTreat=o['inTreat'], dur=median(o.get('durs', [])), dn=len(o.get('durs', []))))
        return [r for r in rows if r['inTreat'] or r['n'] > 0]

    def tiles(self, C, rows, call):
        """ヘッダーとサマリーの数値（JS の render() の前半）。"""
        treat = [r for r in rows if r['inTreat']]
        fix, est = sum(r['nomFix'] for r in rows), sum(r['nomEst'] for r in rows)
        tot_pts = sum(r['pts'] for r in treat)
        all_n = sum(r['n'] for r in rows)
        all_sc = sum(r['avg'] * r['n'] for r in rows if r['avg'] is not None)
        one = bool(C['day']) and not C['isM']
        no_p = one and C['day'] not in C['pDates']
        no_s = one and C['day'] not in C['sDates']
        return dict(period=(C['p0'], C['p1'], C['ndays'] or len(C['dates'])), nurses=len(treat), cnt=sum(r['cnt'] for r in treat),
                    pts=tot_pts, nom=None if no_p else fix + est, nomFix=None if no_p else fix, nomEst=None if no_p else est,
                    rate=None if no_p or not tot_pts else (fix + est) / tot_pts,
                    voc=to_fixed2(all_sc / all_n) if all_n else None, voc_n=all_n,
                    flagged=sorted(r['name'] for r in rows if r['st'] in ('crit', 'warn')),
                    gapP=[d for d in call['dates'] if d not in call['pDates']],
                    gapS=[d for d in call['dates'] if d not in call['sDates']],
                    unassigned=C['est_unassigned'], noS=no_s)


def median(xs):
    """JS の med() と同じ（偶数個は真ん中2つの平均。秒の整数なので丸めの差は出ない）。"""
    if not xs:
        return None
    s, k = sorted(xs), len(xs) // 2
    return s[k] if len(xs) % 2 else (s[k - 1] + s[k]) / 2


def minutes(sec):
    """画面の表示（JS の Math.round(sec/60)+'分'）。"""
    return '–' if sec is None else f'{math.floor(sec / 60 + 0.5)}分'


def to_fixed2(v):
    """JS の toFixed(2) と同じ丸め（2進数の値そのままで四捨五入。4.625 -> '4.63'。Python の :.2f は '4.62'）。"""
    return str(decimal.Decimal(v).quantize(decimal.Decimal('0.01'), decimal.ROUND_HALF_UP))


def months(dates):
    """表示できる月（'YYYY-MM'）。"""
    return sorted({d[:7] for d in dates if d})


# 月の切り替え（2026-11-02、オーナーの依頼）: 9月からの全期間を1ページに持ち、全期間・月・日で切り替える。
# 公開中のページの JS をこの置き換えで直す（何度かけても同じ）。compute() / tiles() の Python 再現も同じ形にしてある。
MONTH_JS = [
    ("  if(day) proc=proc.filter(l=>l.date===day);",
     "  const isM=!!day&&day.length===7, inSel=d=>!day||(isM?String(d||'').startsWith(day):d===day);\n"
     "  if(day) proc=proc.filter(l=>inSel(l.date));"),
    ("    if(day && v.d!==day) continue;", "    if(day && !inSel(v.d)) continue;"),
    ("  const p0=day||dates[0], p1=day||dates[dates.length-1];",
     "  const sel=dates.filter(inSel);\n"
     "  const p0=isM?sel[0]:(day||dates[0]), p1=isM?sel[sel.length-1]:(day||dates[dates.length-1]);"),
    ("  return {proc,dates,roster,respList,shine,p0,p1,day,estUnassigned,nurseSet,pDates,sDates};",
     "  return {proc,dates,roster,respList,shine,p0,p1,day,isM,ndays:isM?sel.length:null,estUnassigned,nurseSet,pDates,sDates};"),
    ("  const noP=C.day&&!C.pDates.has(C.day), noS=C.day&&!C.sDates.has(C.day);",
     "  const one=C.day&&!C.isM; const noP=one&&!C.pDates.has(C.day), noS=one&&!C.sDates.has(C.day);"),
    ("施術・購入：${C.day?C.day.replaceAll", "施術・購入：${one?C.day.replaceAll"),
    ("+'（'+C.dates.length+'日間）'}", "+'（'+(C.ndays||C.dates.length)+'日間）'}"),
    ("(C.day?'同日の予約分':'施術と同期間の予約分')", "(one?'同日の予約分':'施術と同期間の予約分')"),
    ("  heat('daily',allTreat,CALL.dates,r=>d=>r.days[d]||0,d=>md(d)+'('+wd(d)+')',day);",
     "  heat('daily',allTreat,scopeDates(),r=>d=>r.days[d]||0,d=>md(d)+'('+wd(d)+')',C.isM?null:day);"),
    ("  const opts=[[null,'全期間'],...CALL.dates.map(d=>[d,md(d)])];",
     "  const months=[...new Set(CALL.dates.map(d=>d.slice(0,7)))];\n"
     "  const opts=[[null,'全期間'],...months.map(m=>[m,(+m.slice(5))+'月']),...scopeDates().map(d=>[d,md(d)])];"),
    ("function setDay(d){",
     "// 日のボタンと日別のヒートマップは、選んでいる月（全期間のときは最新の月）の日だけ\n"
     "function scopeDates(){ const ms=[...new Set(CALL.dates.map(d=>d.slice(0,7)))]; const m=day?day.slice(0,7):ms[ms.length-1];"
     " return CALL.dates.filter(d=>d.startsWith(m)); }\n"
     "function setDay(d){"),
]
MONTH_MARK = 'function scopeDates()'


# 月のボタンが増えても「全期間」「9月」が縦に潰れないように（ボタンは折り返さず、バーは横にスクロール）
MONTH_CSS = '#dayBar{overflow-x:auto;max-width:100%}#dayBar button{white-space:nowrap;flex:0 0 auto}'


def migrate_months(html):
    """公開中のページの JS を、全期間・月・日の切り替えに直す（済んでいれば何もしない）。"""
    if MONTH_CSS not in html:
        if html.count('</style>') < 1:
            raise SystemExit('STOP: the page has no </style>; cannot add the month-bar CSS')
        html = html.replace('</style>', MONTH_CSS + '\n</style>', 1)
    if MONTH_MARK in html:
        return html
    for old, new in MONTH_JS:
        if html.count(old) != 1:
            raise SystemExit(f'STOP: the page JS is not what migrate_months expects: {old[:60]!r}')
        html = html.replace(old, new)
    return html


# 施術時間の目安（2026-11-17、オーナーの依頼）: 看護師別の表に「施術時間（目安）」の列を足す。
# T の明細の6列目（秒。aggregate.durations）の中央値。Excel 版の行には無いので「–」。何度かけても同じ。
DUR_NOTE = ('        <p><b>施術時間（目安）</b>：1件あたりの所要時間の中央値。KOS に施術の開始時刻が無いため、'
            '「施術者の割当（同じ来院で前の施術があればその完了）」から「完了」までの時間で代用。'
            '入力の遅れなどで実際の施術時間とはずれるので、看護師間の比較の目安として見る。'
            '0分以下・120分超は除外。n は計算できた件数。</p>\n')
DUR_JS = [
    ("    const [g,cat,item,tanto,couns]=r;", "    const [g,cat,item,tanto,couns,dur]=r;"),
    ("cat, item, tanto:canon(tanto)});", "cat, item, tanto:canon(tanto), dur:typeof dur==='number'?dur:null});"),
    ("nomFix:0,nomEst:0,scores:[],comments:[],mentions:0,inTreat:false}); return roster.get(n); };",
     "nomFix:0,nomEst:0,scores:[],comments:[],mentions:0,inTreat:false,durs:[]}); return roster.get(n); };"),
    ("o.cats[c]=(o.cats[c]||0)+1; }", "o.cats[c]=(o.cats[c]||0)+1; if(l.dur!=null) o.durs.push(l.dur); }"),
    ("days:{},cats:{},nomFix:0,nomEst:0,inTreat:false};", "days:{},cats:{},nomFix:0,nomEst:0,inTreat:false,durs:[]};"),
    ("ment,comments,inTreat:o.inTreat});", "ment,comments,inTreat:o.inTreat,dur:med(o.durs||[]),dn:(o.durs||[]).length});"),
    ("function build(C, vocMode){",
     "// 中央値（施術時間の目安）。偶数個は真ん中2つの平均\n"
     "const med = xs => { if(!xs.length) return null; const s=[...xs].sort((a,b)=>a-b), k=s.length>>1; return s.length%2?s[k]:(s[k-1]+s[k])/2; };\n"
     "function build(C, vocMode){"),
    ("['assist','医師施術の担当','r'],", "['assist','医師施術の担当','r'],['dur','施術時間（目安）','r'],"),
    ("      <td class=\"r num\">${r.assist||'–'}</td>\n",
     "      <td class=\"r num\">${r.assist||'–'}</td>\n"
     "      <td class=\"r\"><span class=\"num\">${r.dur==null?'–':Math.round(r.dur/60)+'分'}</span> <span class=\"sub\">n=${r.dn}</span></td>\n"),
    ("        <p id=\"excl\"></p>", DUR_NOTE + "        <p id=\"excl\"></p>"),
]
DUR_MARK = 'const med = xs =>'


def migrate_duration(html):
    """公開中のページに「施術時間（目安）」の列を足す（済んでいれば何もしない）。"""
    if DUR_MARK in html:
        return html
    for old, new in DUR_JS:
        if html.count(old) != 1:
            raise SystemExit(f'STOP: the page is not what migrate_duration expects: {old[:60]!r}')
        html = html.replace(old, new)
    return html


def views(html_or_embed, cfg):
    """ページで選べる表示（全期間・各月・各日 × VOC 2種）ごとの (tiles, rows)。"""
    D = html_or_embed if isinstance(html_or_embed, dict) else get_embed(html_or_embed)
    calc = Calc(cfg)
    call = calc.compute(D)
    out = {}
    for day in [None] + months(call['dates']) + call['dates']:
        C = call if day is None else calc.compute(D, day)
        for mode in ('same', 'all'):
            rows = calc.board(C, mode)
            out[(day or 'ALL', mode)] = (calc.tiles(C, rows, call), {r['name']: r for r in rows})
    return out
