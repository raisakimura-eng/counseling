"""Rules of the 着地予想ダッシュボード that are clinic settings rather than code.

Every value here was checked against the published page (see README.md, 「集計ルール」).
"""
import re

SITE = 'naaclinic'  # Netlify site of the page (no password: the page shows no patient names)

# Visits excluded from 着地結果・客単価・要因 (the page: 「スタッフ（本部スタッフ・クリニックスタッフ）と
# インフルエンサー・PR・アンバサダー枠の来院は、予想・客単価などの分析から除いています」).
# Identified by the KOS 患者カテゴリ (visitorCategoryNames). 売上目標の進捗 still uses the whole clinic.
EXCLUDE_CATEGORIES = {'NaA+HPMS': 'staff', 'インフルエンサー': 'influencer'}
# Optional extra rule: visitors whose 患者メモ matches this are treated as PR (the blog/AURA monitor
# visitor is excluded on the published page but has no category in KOS). None = categories only.
EXCLUDE_VISITOR_MEMO = re.compile(r'ブログにのせる')

# 来院率 assumed by the 着地予想 (current logic on the page: 初診90%・再診95%)
RATE = {'初診': 0.9, '再診': 0.95}
TYPES = ('初診', '再診')

# Statuses
VISITED = ('COMPLETED', 'IN_PROGRESS')
ACTIVE = ('RESERVED', 'IN_PROGRESS', 'COMPLETED')
CANCELLED = ('CANCELED', 'NO_SHOW')

# 施術: 「診察・麻酔・指名料は除いています」
PROC_EXCLUDE = re.compile(r'診察|麻酔|指名')

# 高単価施術（HPB掲載メニュー）: label -> regex on purchase/requested product + option titles.
# 「リジュランはNaA式減痛・ダーマシャイン・リジュランiを含みます」
HPB_MENUS = [
    ('リジュラン', re.compile(r'リジュラン')),
    ('リボーン', re.compile(r'リボーン')),
    ('Re2O(ブナジュ)', re.compile(r'Re2O|ブナジュ')),
    ('ヒロウェーブ', re.compile(r'ヒロウェーブ')),
    ('Juveacell', re.compile(r'Juveacell|ジュベアセル', re.I)),
    ('ザーフ', re.compile(r'ザーフ')),
    ('ウルセラピープライム', re.compile(r'ウルセラ')),
    ('デンシティ', re.compile(r'デンシティ')),
    ('ミント', re.compile(r'ミント')),
    ('テスリフト', re.compile(r'テスリフト')),
    ('ジェンバー', re.compile(r'ジェンバー')),
    ('スペシャルパッケージプラン', re.compile(r'スペシャルパッケージ')),
]

AGE_BANDS = ['10代', '20代', '30代', '40代', '50代', '60代', '70代']
LEAD_BUCKETS = ['当日', '前日', '2〜7日前', '8〜30日前', '31日以上前', '不明']

# Memo parsing for the timing of cancellations (used only when no 0:00 snapshot exists for the day)
CANCEL_LINE = re.compile(r'キャンセル|ｷｬﾝｾﾙ|ムキャン|無キャン|不通|来院な|来院され|取り消|取消|ノーショー')
SAME_DAY_WORDS = re.compile(r'当日キャンセル|当日ｷｬﾝｾﾙ|当日のキャンセル|来院なく|来院なし|来院されず|来院がなく|ムキャン|無キャン|ノーショー')

# 「9月まとめ」 (SUMMARY) was written by hand before automation; later months get SUMMARIES entries
LEGACY_SUMMARY = '2026-09'


class Targets(dict):
    """Monthly sales targets from targets.json. A month without its own entry uses "default"
    (the owner's rule, 2026-10-12: if no target is shared for a month, use 55,000,000円)."""

    def get(self, ym, fallback=None):
        return super().get(ym) or super().get('default') or fallback


def load_targets(path):
    import json
    return Targets(json.load(open(path)))
