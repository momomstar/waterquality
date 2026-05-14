import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl

FUZZY_VERSION = "3.0.1"
# v3.0.1 (Hospital edition — bug fixes from v3.0.0):
#   - แก้ค่ามาตรฐานให้ตรงตามประกาศกระทรวงทรัพยากรฯ พ.ศ. 2567 "อาคารสถานพยาบาล"
#   - pH: 5.5-9.0 (เดิม 5.0-9.0 ผิด)
#   - BOD ประเภท ง: 100 (เดิม 50 ผิด — มาตรฐานสำหรับโรงพยาบาล/พาณิชย์ ไม่ใช่อยู่อาศัย)
#   - O&G ประเภท ง: 50 (เดิม 20 ผิด — เช่นเดียวกัน)
#   - Free Cl2: max ≤1.0 (เดิม range 0.2-1.0 อิง HA แต่กฎหมาย 2567 เป็น max-only)
#   - COD: ทำเป็น unregulated everywhere (มาตรฐาน 2567 ไม่กำหนด)
#   - Sulfide/Cl2 MF: ที่ S = ผ่านพอดี → μ(safe)=1.0 (legal-aligned)
#   - เพิ่ม R12 (Hospital-critical TCB/FCB rule) อ้างอิง WHO (2017)
#   - แก้ pH MF ให้ที่ pH=5.5 และ 9.0 → μ(neutral_core)=1.0 (ผ่านพอดี)
#
# 🐛 BUG FIXES ใน v3.0.1:
#   [Bug 1] pH=5.5 ขอบล่างพอดี → Score 78.6 (Good) แทนที่จะเป็น 91 (Excellent)
#           Root cause: acidic_slight=trimf[5.0,5.3,5.6] overlap neutral_core ที่ 5.5
#                       → μ(acidic_slight)=0.333 ที่ pH=5.5 → R3 ติด → ดึงคะแนนลง
#           Fix: เลื่อน acidic_slight → trimf[5.0, 5.25, 5.5] — จบที่ 5.5 พอดี (μ=0)
#                สมมาตรกับ alkaline_slight = trimf[9.0, 9.3, 9.6]
#
#   [Bug 2] อาคาร ง score ค้างที่ 58.5 ไม่ว่าใส่ค่าอะไร
#           Root cause: (a) _make_unregulated_max_mf ใช้ trimf[u_max,u_max,u_max]
#                          ซึ่งจริง ๆ μ=1.0 ที่ x=u_max (ไม่ใช่ 0)
#                       (b) ใน Cl2 unregulated เรียก _make_unregulated_max_mf ก่อน
#                          แล้วเขียนทับด้วย normal_core/low_strong/etc.
#                          → safe/low/medium/high ที่ค้างจาก step (a) ยังอยู่
#                          → membership ทุก term = 1.0 พร้อมกัน → Mamdani เพี้ยน
#           Fix: (a) ใช้ np.zeros_like(var.universe) เป็น true-zero MF
#                (b) Cl2 unregulated ตั้ง terms 5 ตัวตรง ๆ — ไม่เรียก _make_unregulated_max_mf


# ============================================================
# มาตรฐานน้ำทิ้งจากอาคารสถานพยาบาล พ.ศ. 2567 — ประเภท ก, ข, ค, ง
# ============================================================
BUILDING_TYPES = ['ก', 'ข', 'ค', 'ง']
DEFAULT_BUILDING_TYPE = 'ก'

BUILDING_STANDARDS = {
    'ก': {
        'pH':      {'min': 5.5, 'max': 9.0},
        'BOD':     {'max': 20},
        'COD':     None,
        'TSS':     {'max': 30},
        'TDS':     {'max': 1000},
        'O&G':     {'max': 20},
        'TKN':     {'max': 35},
        'Sulfide': {'max': 1.0},
        'TCB':     {'max': 5000},
        'FCB':     {'max': 1000},
        'Cl2':     {'max': 1.0},
    },
    'ข': {
        'pH':      {'min': 5.5, 'max': 9.0},
        'BOD':     {'max': 30},
        'COD':     None,
        'TSS':     {'max': 40},
        'TDS':     {'max': 1000},
        'O&G':     {'max': 20},
        'TKN':     {'max': 35},
        'Sulfide': {'max': 1.0},
        'TCB':     {'max': 5000},
        'FCB':     {'max': 1000},
        'Cl2':     {'max': 1.0},
    },
    'ค': {
        'pH':      {'min': 5.5, 'max': 9.0},
        'BOD':     {'max': 40},
        'COD':     None,
        'TSS':     {'max': 50},
        'TDS':     {'max': 1300},
        'O&G':     {'max': 20},
        'TKN':     {'max': 40},
        'Sulfide': {'max': 1.0},
        'TCB':     None,
        'FCB':     None,
        'Cl2':     None,
    },
    'ง': {
        'pH':      {'min': 5.5, 'max': 9.0},
        'BOD':     {'max': 100},
        'COD':     None,
        'TSS':     {'max': 60},
        'TDS':     None,
        'O&G':     {'max': 50},
        'TKN':     None,
        'Sulfide': None,
        'TCB':     None,
        'FCB':     None,
        'Cl2':     None,
    },
}


# ============================================================
# WQI SCORE BANDS — อ้างอิง Hallock (2002) + Brown et al. (1970)
# ============================================================
WQI_BANDS = [
    {'name': 'Excellent', 'min': 80, 'max': 100,
     'msg': 'คุณภาพน้ำดีเยี่ยม ผ่านด้วยดี มีกันชนมาก ✅✅'},
    {'name': 'Good',      'min': 60, 'max': 79,
     'msg': 'คุณภาพน้ำดี ผ่านมาตรฐาน แต่ควรติดตาม ✅'},
    {'name': 'Fair',      'min': 40, 'max': 59,
     'msg': 'เฝ้าระวัง ใกล้เกินมาตรฐาน ⚠️'},
    {'name': 'Poor',      'min': 20, 'max': 39,
     'msg': 'เกินมาตรฐาน ต้องแก้ไขระบบบำบัด ❌'},
    {'name': 'Very Poor', 'min':  0, 'max': 19,
     'msg': 'เกินมาตรฐานมาก ต้องแก้ไขเร่งด่วน ❌❌'},
]


def score_to_wqi_band(score):
    if score is None:
        return 'No Data'
    try:
        s = float(score)
    except Exception:
        return 'No Data'
    if s >= 80: return 'Excellent'
    if s >= 60: return 'Good'
    if s >= 40: return 'Fair'
    if s >= 20: return 'Poor'
    return 'Very Poor'


def score_to_wqi_message(score):
    band = score_to_wqi_band(score)
    for b in WQI_BANDS:
        if b['name'] == band:
            return b['msg']
    return ''


_FUZZY_CACHE = {}

def get_fuzzy_system(building_type=DEFAULT_BUILDING_TYPE):
    bt = (building_type or DEFAULT_BUILDING_TYPE).strip()
    if bt not in BUILDING_STANDARDS:
        bt = DEFAULT_BUILDING_TYPE
    if bt not in _FUZZY_CACHE:
        _FUZZY_CACHE[bt] = WaterQualityFuzzySystem(building_type=bt)
    return _FUZZY_CACHE[bt]


def get_param_zones(building_type=DEFAULT_BUILDING_TYPE):
    """คืน dict zones ของทุกพารามิเตอร์สำหรับประเภทอาคาร — ใช้ใน reference table"""
    bt = (building_type or DEFAULT_BUILDING_TYPE).strip()
    if bt not in BUILDING_STANDARDS:
        bt = DEFAULT_BUILDING_TYPE
    fs = get_fuzzy_system(bt)
    stds = BUILDING_STANDARDS[bt]

    PARAM_DISPLAY = [
        ('pH',      'pH',      '–'),
        ('BOD',     'BOD',     'mg/L'),
        ('COD',     'COD',     'mg/L'),
        ('TSS',     'TSS',     'mg/L'),
        ('TDS',     'TDS',     'mg/L'),
        ('O&G',     'O&G',     'mg/L'),
        ('TKN',     'TKN',     'mg/L'),
        ('Sulfide', 'Sulfide', 'mg/L'),
        ('TCB',     'TCB',     'MPN/100mL'),
        ('FCB',     'FCB',     'MPN/100mL'),
        ('Cl2',     'Cl₂',     'mg/L'),
    ]

    def _zone(u, mf, threshold=0.99):
        mask = mf >= threshold
        if not mask.any():
            return None
        return (float(u[mask].min()), float(u[mask].max()))

    params_list = []
    for key, disp, unit in PARAM_DISPLAY:
        std = stds.get(key)
        var_attr = key if key != 'O&G' else 'OG'
        var = getattr(fs, var_attr, None)

        if std is None:
            params_list.append({
                'name': disp, 'key': key, 'unit': unit,
                'standard_text': 'ไม่กำหนด',
                'standard_min': None, 'standard_max': None,
                'regulated': False,
                'full_score': None, 'transition': None,
                'medium': None, 'high': None,
                'universe_max': float(var.universe.max()) if var is not None else 100,
            })
            continue

        u = var.universe
        umax = float(u.max())

        if key == 'pH':
            full = _zone(u, var['neutral_core'].mf)
            std_txt = f"{std['min']}–{std['max']}"
            entry = {
                'name': disp, 'key': key, 'unit': unit,
                'standard_text': std_txt,
                'standard_min': std.get('min'),
                'standard_max': std.get('max'),
                'regulated': True,
                'full_score': full, 'transition': None,
                'medium': None, 'high': None,
                'universe_max': umax,
            }
        elif key == 'Cl2':
            full = _zone(u, var['normal_core'].mf)
            mx = std.get('max')
            try:
                std_txt = f'≤ {mx:,}' if mx is not None and mx >= 1000 else f'≤ {mx}'
            except Exception:
                std_txt = f'≤ {mx}'
            entry = {
                'name': disp, 'key': key, 'unit': unit,
                'standard_text': std_txt,
                'standard_min': None,
                'standard_max': mx,
                'regulated': True,
                'full_score': full, 'transition': None,
                'medium': None, 'high': None,
                'universe_max': umax,
            }
        else:
            safe_mf = var['safe'].mf
            full = _zone(u, safe_mf)
            trans_mask = (safe_mf < 0.99) & (safe_mf >= 0.01)
            transition = (float(u[trans_mask].min()), float(u[trans_mask].max())) if trans_mask.any() else None
            med_mf = var['medium'].mf if 'medium' in var.terms else None
            high_mf = var['high'].mf if 'high' in var.terms else None
            medium_zone = _zone(u, med_mf, 0.5) if med_mf is not None else None
            high_zone = _zone(u, high_mf, 0.5) if high_mf is not None else None

            mx = std.get('max')
            try:
                std_txt = f'≤ {mx:,}' if mx is not None and mx >= 1000 else f'≤ {mx}'
            except Exception:
                std_txt = f'≤ {mx}'

            entry = {
                'name': disp, 'key': key, 'unit': unit,
                'standard_text': std_txt,
                'standard_min': std.get('min'),
                'standard_max': mx,
                'regulated': True,
                'full_score': full,
                'transition': transition,
                'medium': medium_zone,
                'high': high_zone,
                'universe_max': umax,
            }
        params_list.append(entry)

    return {'building_type': bt, 'params': params_list}


class WaterQualityFuzzySystem:
    """Pure Mamdani Fuzzy Logic System — รองรับมาตรฐาน พ.ศ. 2567 ก/ข/ค/ง
    v3.0.1: bug fixes from v3.0.0 — pH 5.5 boundary + unregulated zero-MF"""

    def __init__(self, building_type=DEFAULT_BUILDING_TYPE):
        bt = (building_type or DEFAULT_BUILDING_TYPE).strip()
        if bt not in BUILDING_STANDARDS:
            bt = DEFAULT_BUILDING_TYPE
        self.building_type = bt

        raw_standards = BUILDING_STANDARDS[bt]
        self.regulated = {k: (v is not None) for k, v in raw_standards.items()}
        self.standards = {}
        for k, v in raw_standards.items():
            if v is not None:
                self.standards[k] = dict(v)
            else:
                self.standards[k] = {'max': 1.0}

        self.delta0_default = 0.10
        self.delta1_default = 0.10

        # GUM k=2 × CV per APHA Standard Methods 23rd Ed.
        self.delta0_override = {
            'pH': 0.05, 'BOD': 0.30, 'COD': 0.28, 'TSS': 0.25, 'TDS': 0.15,
            'O&G': 0.30, 'TKN': 0.30, 'Sulfide': 0.30,
            'TCB': 0.30, 'FCB': 0.30, 'Cl2': 0.20,
        }
        self.delta1_override = {
            'BOD': 0.50, 'COD': 0.50, 'TSS': 0.50,
            'FCB': 1.00, 'TCB': 1.00, 'O&G': 0.50,
            'TKN': 0.50, 'TDS': 0.30, 'Cl2': 0.50,
        }
        self.delta2 = {
            'BOD': 1.0, 'COD': 1.0, 'TSS': 1.0, 'O&G': 1.0, 'TKN': 1.0,
            'Sulfide': 1.0, 'FCB': 1.5, 'TCB': 1.5, 'TDS': 2.0, 'Cl2': 2.0,
        }

        self._build_fuzzy_system()

    @staticmethod
    def _clamp(v, vmin, vmax):
        try:
            x = float(v)
        except Exception:
            return float(vmin)
        if x < vmin: return float(vmin)
        if x > vmax: return float(vmax)
        return x

    @staticmethod
    def _clamp01(x):
        try:
            x = float(x)
        except Exception:
            return 0.0
        if x < 0.0: return 0.0
        if x > 1.0: return 1.0
        return x

    def is_regulated(self, user_key):
        return bool(self.regulated.get(user_key, True))

    def _risk_percent_max_type(self, m):
        mu_med = float(m.get('medium', 0.0))
        mu_high = float(m.get('high', 0.0))
        mu_vh = float(m.get('very_high', 0.0))
        risk = (0.5 * mu_med) + (1.0 * mu_high) + (1.2 * mu_vh)
        return round(self._clamp01(risk / 1.2) * 100, 1)

    def _risk_percent_ph(self, m):
        s = max(float(m.get('acidic_slight', 0.0)),
                float(m.get('alkaline_slight', 0.0)))
        st = max(float(m.get('acidic_strong', 0.0)),
                 float(m.get('alkaline_strong', 0.0)))
        return round(self._clamp01(0.5 * s + 1.0 * st) * 100, 1)

    @staticmethod
    def _status_from_risk_percent(r):
        r = float(r)
        if r < 25: return 'Pass'
        if r < 60: return 'Near Limit'
        return 'Fail'

    @staticmethod
    def _zero_mf(universe):
        """🔧 v3.0.1 FIX: true-zero MF (np.zeros_like)
        แทนการใช้ trimf[umax,umax,umax] ซึ่งมี μ=1.0 ที่ x=umax"""
        return np.zeros_like(universe, dtype=float)

    def _make_unregulated_max_mf(self, var, has_very_high=False):
        """🔧 v3.0.1 FIX: ใช้ _zero_mf เพื่อให้ μ=0 จริงที่ทุกจุด"""
        u_min = float(var.universe.min())
        u_max = float(var.universe.max())
        var['safe']   = fuzz.trapmf(var.universe, [u_min, u_min, u_max, u_max])
        var['low']    = self._zero_mf(var.universe)
        var['medium'] = self._zero_mf(var.universe)
        var['high']   = self._zero_mf(var.universe)
        if has_very_high:
            var['very_high'] = self._zero_mf(var.universe)

    def _make_low_medium_high(self, var, param_name, delta0=None, delta1=None, delta2=None):
        """max-type MF — "ยิ่งมากยิ่งแย่"
        Legal-aligned: ที่ x=S → μ(safe)=1.0 (≤S = ผ่านตามกฎหมาย)"""
        if not self.regulated.get(param_name, True):
            has_vh = (param_name in ('TCB', 'FCB'))
            self._make_unregulated_max_mf(var, has_very_high=has_vh)
            return

        S = float(self.standards[param_name]['max'])
        d0 = float(delta0) if delta0 is not None else self.delta0_override.get(param_name, self.delta0_default)
        d1 = float(delta1) if delta1 is not None else self.delta1_override.get(param_name, self.delta1_default)
        d2 = float(delta2) if delta2 is not None else self.delta2.get(param_name, 1.0)

        u_min = float(var.universe.min())
        u_max = float(var.universe.max())

        e = S * d0
        s_end = min(S + e, u_max)
        c = min(S * (1.0 + d1), u_max)
        d = min(S * (1.0 + d2), u_max)
        s_end = max(s_end, S)
        c = max(c, s_end)
        d = max(d, c)

        var['safe'] = fuzz.trapmf(var.universe, [u_min, u_min, S, s_end])

        a = max(u_min, S * (1.0 - d0))
        var['low'] = fuzz.trapmf(var.universe, [u_min, u_min, a, S])

        m_peak_lo = min(S + e/2.0, c)
        m_peak_hi = c
        m_end = min(d, u_max)
        m_peak_lo = max(S, min(m_peak_lo, m_peak_hi))
        var['medium'] = fuzz.trapmf(var.universe, [S, m_peak_lo, m_peak_hi, m_end])

        h_start = max(s_end, m_peak_lo)
        if param_name in ('TCB', 'FCB'):
            var['high'] = fuzz.trapmf(var.universe, [h_start, c, d, d])
            var['very_high'] = fuzz.trapmf(var.universe, [d, d, u_max, u_max])
        else:
            var['high'] = fuzz.trapmf(var.universe, [h_start, c, u_max, u_max])

    def _make_sulfide_mf(self, var):
        """Sulfide MF: ก/ข/ค กำหนด ≤1.0, ง ไม่กำหนด"""
        if not self.regulated.get('Sulfide', True):
            self._make_unregulated_max_mf(var, has_very_high=False)
            return
        u_max = float(var.universe.max())
        var['safe']   = fuzz.trapmf(var.universe, [0.0, 0.0, 1.0, 1.1])
        var['low']    = fuzz.trapmf(var.universe, [0.0, 0.0, 0.7, 1.0])
        var['medium'] = fuzz.trapmf(var.universe, [1.0, 1.1, 1.4, 1.7])
        var['high']   = fuzz.trapmf(var.universe, [1.4, 1.7, u_max, u_max])

    def _make_ph_mf(self, var):
        """pH MFs — มาตรฐาน 2567: 5.5–9.0
        🔧 v3.0.1 FIX: acidic_slight = trimf[5.0, 5.25, 5.5] — จบที่ 5.5 พอดี
        (v3.0.0 ใช้ [5.0, 5.3, 5.6] → μ=0.333 ที่ pH=5.5 → bug)"""
        var['acidic_strong']   = fuzz.trapmf(var.universe, [0.0, 0.0, 5.0, 5.4])
        var['acidic_slight']   = fuzz.trimf(var.universe,  [5.0, 5.25, 5.5])
        var['neutral_core']    = fuzz.trapmf(var.universe, [5.4, 5.5, 9.0, 9.1])
        var['alkaline_slight'] = fuzz.trimf(var.universe,  [9.0, 9.3, 9.6])
        var['alkaline_strong'] = fuzz.trapmf(var.universe, [9.5, 9.8, 14.0, 14.0])

    def _make_cl2_mf(self, var):
        """Cl2 MFs — มาตรฐาน 2567: ≤1.0 (max-only) สำหรับ ก/ข, ค/ง ไม่กำหนด

        🔧 v3.0.1 FIX: ใน unregulated case ตั้ง 5 terms ตรง ๆ
        ไม่เรียก _make_unregulated_max_mf (ซึ่งจะสร้าง safe/low/medium/high ค้างไว้)"""
        u_min = float(var.universe.min())
        u_max = float(var.universe.max())

        if not self.regulated.get('Cl2', True):
            var['low_strong']  = self._zero_mf(var.universe)
            var['low_slight']  = self._zero_mf(var.universe)
            var['normal_core'] = fuzz.trapmf(var.universe, [u_min, u_min, u_max, u_max])
            var['high_slight'] = self._zero_mf(var.universe)
            var['high_strong'] = self._zero_mf(var.universe)
            return

        var['low_strong']  = self._zero_mf(var.universe)
        var['low_slight']  = self._zero_mf(var.universe)
        var['normal_core'] = fuzz.trapmf(var.universe, [0.0, 0.0, 1.0, 1.2])
        var['high_slight'] = fuzz.trapmf(var.universe, [1.0, 1.2, 1.5, 1.8])
        var['high_strong'] = fuzz.trapmf(var.universe, [1.5, 1.8, u_max, u_max])

    def _build_fuzzy_system(self):
        self.pH      = ctrl.Antecedent(np.arange(0,    14.1,   0.1), 'pH')
        self.BOD     = ctrl.Antecedent(np.arange(0,    301,    0.1), 'BOD')
        self.COD     = ctrl.Antecedent(np.arange(0,    1001,   1),   'COD')
        self.TSS     = ctrl.Antecedent(np.arange(0,    501,    0.1), 'TSS')
        self.TDS     = ctrl.Antecedent(np.arange(0,    20001,  1),   'TDS')
        self.OG      = ctrl.Antecedent(np.arange(0,    201,    0.1), 'OG')
        self.TKN     = ctrl.Antecedent(np.arange(0,    501,    1),   'TKN')
        self.Sulfide = ctrl.Antecedent(np.arange(0,    10.1,   0.01),'Sulfide')
        self.TCB     = ctrl.Antecedent(np.arange(0,    100001, 1),   'TCB')
        self.FCB     = ctrl.Antecedent(np.arange(0,    50001,  1),   'FCB')
        self.Cl2     = ctrl.Antecedent(np.arange(0,    10.1,   0.1), 'Cl2')

        self.Quality = ctrl.Consequent(np.arange(0, 101, 1), 'Quality')

        self._make_ph_mf(self.pH)
        self._make_low_medium_high(self.BOD, 'BOD')
        self._make_low_medium_high(self.COD, 'COD')
        self._make_low_medium_high(self.TSS, 'TSS')
        self._make_low_medium_high(self.TDS, 'TDS')
        self._make_low_medium_high(self.OG,  'O&G')
        self._make_low_medium_high(self.TKN, 'TKN')
        self._make_low_medium_high(self.TCB, 'TCB')
        self._make_low_medium_high(self.FCB, 'FCB')
        self._make_sulfide_mf(self.Sulfide)
        self._make_cl2_mf(self.Cl2)

        y = self.Quality.universe
        self.Quality['very_poor'] = fuzz.trapmf(y, [0,   0,   12,  18])
        self.Quality['poor']      = fuzz.trapmf(y, [16,  22,  32,  38])
        self.Quality['fair']      = fuzz.trapmf(y, [36,  42,  52,  58])
        self.Quality['good']      = fuzz.trapmf(y, [56,  64,  72,  78])
        self.Quality['excellent'] = fuzz.trapmf(y, [76,  90,  100, 100])

        self.rules_meta = []
        rules = []
        AND = lambda *xs: min(xs) if xs else 0.0
        OR  = lambda *xs: max(xs) if xs else 0.0

        def add_rule(name, ant_expr, conseq_term, strength_fn):
            rules.append(ctrl.Rule(ant_expr, conseq_term))
            self.rules_meta.append({
                'name': name, 'consequent': conseq_term.label,
                'strength_fn': strength_fn,
            })

        # R1: EXCELLENT
        add_rule(
            "R1 EXCELLENT: ทุก param=safe + pH neutral + Cl2 normal",
            (self.pH['neutral_core'] & self.Cl2['normal_core'] &
             self.BOD['safe'] & self.TSS['safe'] & self.Sulfide['safe'] &
             self.TCB['safe'] & self.FCB['safe'] & self.TKN['safe'] &
             self.OG['safe'] & self.TDS['safe']),
            self.Quality['excellent'],
            lambda M: AND(
                M['pH']['neutral_core'], M['Cl2']['normal_core'],
                M['BOD']['safe'], M['TSS']['safe'], M['Sulfide']['safe'],
                M['TCB']['safe'], M['FCB']['safe'], M['TKN']['safe'],
                M['OG']['safe'], M['TDS']['safe'])
        )

        # R2: GOOD
        secondary_medium = (
            self.Sulfide['medium'] | self.TKN['medium'] | self.OG['medium'] |
            self.TCB['medium'] | self.FCB['medium'] | self.TDS['medium']
        )
        add_rule(
            "R2 GOOD: BOD/TSS=safe + pH/Cl2 ปกติ + secondary medium ≥1",
            (self.pH['neutral_core'] & self.Cl2['normal_core'] &
             self.BOD['safe'] & self.TSS['safe'] & secondary_medium),
            self.Quality['good'],
            lambda M: AND(
                M['pH']['neutral_core'], M['Cl2']['normal_core'],
                M['BOD']['safe'], M['TSS']['safe'],
                OR(M['Sulfide']['medium'], M['TKN']['medium'],
                   M['OG']['medium'], M['TCB']['medium'],
                   M['FCB']['medium'], M['TDS']['medium']))
        )

        # R3: FAIR
        core_medium = (self.BOD['medium'] | self.TSS['medium'])
        slight_abnormal = (
            self.pH['acidic_slight'] | self.pH['alkaline_slight'] |
            self.Cl2['high_slight']
        )
        add_rule(
            "R3 FAIR: BOD/TSS=medium (pH/Cl2 ปกติ) หรือ pH/Cl2 ผิดเล็กน้อย",
            ((self.pH['neutral_core'] & self.Cl2['normal_core'] & core_medium) |
             slight_abnormal),
            self.Quality['fair'],
            lambda M: OR(
                AND(M['pH']['neutral_core'], M['Cl2']['normal_core'],
                    OR(M['BOD']['medium'], M['TSS']['medium'])),
                OR(M['pH']['acidic_slight'], M['pH']['alkaline_slight'],
                   M['Cl2']['high_slight']))
        )

        # R4: POOR
        add_rule(
            "R4 POOR: param ใด=high (เกินมาตรฐาน)",
            (self.BOD['high'] | self.COD['high'] | self.TSS['high'] |
             self.TDS['high'] | self.TKN['high'] | self.OG['high'] |
             self.Sulfide['high'] | self.FCB['high'] | self.TCB['high']),
            self.Quality['poor'],
            lambda M: OR(
                M['BOD']['high'], M['COD']['high'], M['TSS']['high'],
                M['TDS']['high'], M['TKN']['high'], M['OG']['high'],
                M['Sulfide']['high'], M['FCB']['high'], M['TCB']['high'])
        )

        # R5: POOR
        add_rule(
            "R5 POOR: pH/Cl2 ผิดปกติรุนแรง (strong)",
            (self.pH['acidic_strong'] | self.pH['alkaline_strong'] |
             self.Cl2['high_strong']),
            self.Quality['poor'],
            lambda M: OR(M['pH']['acidic_strong'], M['pH']['alkaline_strong'],
                         M['Cl2']['high_strong'])
        )

        # R6: FAIR
        add_rule(
            "R6 FAIR: BOD=medium AND TSS=medium พร้อมกัน",
            (self.BOD['medium'] & self.TSS['medium']),
            self.Quality['fair'],
            lambda M: AND(M['BOD']['medium'], M['TSS']['medium'])
        )

        # R7: VERY POOR
        add_rule(
            "R7 VERY POOR: (FCB&TCB very_high) OR (strong pH/Cl2 + BOD&TSS/TDS/TKN=high)",
            ((self.FCB['very_high'] & self.TCB['very_high']) |
             ((self.pH['acidic_strong'] | self.pH['alkaline_strong'] |
               self.Cl2['high_strong']) &
              self.BOD['high'] &
              (self.TSS['high'] | self.TDS['high'] | self.TKN['high']))),
            self.Quality['very_poor'],
            lambda M: OR(
                AND(M['FCB'].get('very_high', 0.0), M['TCB'].get('very_high', 0.0)),
                AND(OR(M['pH']['acidic_strong'], M['pH']['alkaline_strong'],
                       M['Cl2']['high_strong']),
                    AND(M['BOD']['high'],
                        OR(M['TSS']['high'], M['TDS']['high'], M['TKN']['high']))))
        )

        # R8: VERY POOR (WHO 2017 hospital)
        add_rule(
            "R8 VERY POOR: FCB=very_high (critical hospital health risk, WHO 2017)",
            self.FCB['very_high'], self.Quality['very_poor'],
            lambda M: M['FCB'].get('very_high', 0.0)
        )

        # R9: VERY POOR
        add_rule(
            "R9 VERY POOR: BOD=high AND TKN=high (organic+nutrient system failure)",
            (self.BOD['high'] & self.TKN['high']), self.Quality['very_poor'],
            lambda M: AND(M['BOD']['high'], M['TKN']['high'])
        )

        # R10: POOR
        add_rule(
            "R10 POOR: O&G=high (drainage/grease trap problem)",
            self.OG['high'], self.Quality['poor'],
            lambda M: M['OG']['high']
        )

        # R11: FAIR
        add_rule(
            "R11 FAIR: FCB หรือ TCB=high อย่างเดียว แต่ BOD/TSS/pH/Cl2 ปกติ",
            ((self.FCB['high'] | self.TCB['high']) &
             self.BOD['safe'] & self.TSS['safe'] &
             self.pH['neutral_core'] & self.Cl2['normal_core']),
            self.Quality['fair'],
            lambda M: AND(
                OR(M['FCB']['high'], M['TCB']['high']),
                M['BOD']['safe'], M['TSS']['safe'],
                M['pH']['neutral_core'], M['Cl2']['normal_core'])
        )

        # R12: POOR (WHO 2017 disinfection compromise)
        add_rule(
            "R12 POOR: (TCB high OR FCB high) AND BOD=medium/high (disinfection compromise)",
            ((self.TCB['high'] | self.FCB['high']) &
             (self.BOD['medium'] | self.BOD['high'])),
            self.Quality['poor'],
            lambda M: AND(
                OR(M['TCB']['high'], M['FCB']['high']),
                OR(M['BOD']['medium'], M['BOD']['high']))
        )

        self.control_system = ctrl.ControlSystem(rules)

    def _impute_neutral(self, user_key):
        if user_key == 'pH':
            mn = self.standards['pH'].get('min', 5.5)
            mx = self.standards['pH'].get('max', 9.0)
            return (mn + mx) / 2.0
        return 0.0

    def _fuzzify_all(self, sim_inputs):
        mapping = {
            'pH': self.pH, 'BOD': self.BOD, 'COD': self.COD, 'TSS': self.TSS,
            'TDS': self.TDS, 'OG': self.OG, 'TKN': self.TKN, 'Sulfide': self.Sulfide,
            'TCB': self.TCB, 'FCB': self.FCB, 'Cl2': self.Cl2,
        }
        M = {}
        for key, var in mapping.items():
            v = self._clamp(sim_inputs[key], var.universe.min(), var.universe.max())
            terms = {}
            for term in var.terms:
                terms[term] = float(fuzz.interp_membership(var.universe, var[term].mf, v))
            M[key] = terms
        return M

    def _rule_firing_report(self, M, top_k=12, threshold=1e-6):
        fired = []
        for r in self.rules_meta:
            s = float(r['strength_fn'](M))
            if s > threshold:
                fired.append({
                    'rule': r['name'], 'consequent': r['consequent'],
                    'strength': round(s, 4),
                })
        fired.sort(key=lambda x: x['strength'], reverse=True)
        return fired[:top_k]

    def evaluate_overall(self, parameters: dict):
        param_mapping = {
            'pH': 'pH', 'BOD': 'BOD', 'COD': 'COD', 'TSS': 'TSS', 'TDS': 'TDS',
            'O&G': 'OG', 'TKN': 'TKN', 'Sulfide': 'Sulfide',
            'TCB': 'TCB', 'FCB': 'FCB', 'Cl2': 'Cl2',
        }

        sim_inputs = {}
        imputed = []
        used = []

        for user_key, fuzzy_key in param_mapping.items():
            v = parameters.get(user_key, None)
            if v is None or (isinstance(v, str) and v.strip() == ''):
                v = self._impute_neutral(user_key)
                imputed.append(user_key)
            else:
                used.append(user_key)

            var = getattr(self, fuzzy_key)
            v = self._clamp(v, var.universe.min(), var.universe.max())
            sim_inputs[fuzzy_key] = float(v)

        sim = ctrl.ControlSystemSimulation(self.control_system)
        for k, v in sim_inputs.items():
            sim.input[k] = v

        try:
            sim.compute()
            score = round(float(sim.output['Quality']), 1)
        except Exception as e:
            return {
                'overall_score': None, 'overall_level': 'No Data',
                'band_by_score': 'No Data',
                'overall_message': f'Fuzzy computation error: {e}',
                'parameter_results': {}, 'fuzzy_membership': {},
                'rule_firing': [], 'parameters_used': used,
                'parameters_imputed': imputed,
                'building_type': self.building_type,
            }

        level = score_to_wqi_band(score)
        msg = score_to_wqi_message(score)

        fuzzy_membership = {}
        for fuzzy_key, v in sim_inputs.items():
            try:
                var = getattr(self, fuzzy_key)
                memberships = {}
                for term in var.terms:
                    memberships[term] = round(
                        float(fuzz.interp_membership(var.universe, var[term].mf, v)),
                        3,
                    )
                fuzzy_membership[fuzzy_key] = {'value': v, 'memberships': memberships}
            except Exception:
                pass

        reverse_mapping = {v: k for k, v in param_mapping.items()}
        parameter_results = {}

        for fuzzy_key, data in fuzzy_membership.items():
            user_key = reverse_mapping.get(fuzzy_key, fuzzy_key)
            memberships = data.get('memberships', {}) or {}
            value = data.get('value', None)
            if not memberships:
                continue

            dominant_term = max(memberships, key=memberships.get)
            dominant_mu = round(float(memberships[dominant_term]), 3)

            is_reg = self.is_regulated(user_key)

            if not is_reg:
                parameter_results[user_key] = {
                    'value': value, 'status': 'ไม่กำหนด',
                    'risk_percent': None, 'dominant_term': 'unregulated',
                    'dominant_mu': 1.0, 'memberships': memberships,
                    'imputed': (user_key in imputed), 'regulated': False,
                }
                continue

            if fuzzy_key == 'pH':
                risk_percent = self._risk_percent_ph(memberships)
            elif fuzzy_key == 'Cl2':
                mu_slight = float(memberships.get('high_slight', 0.0))
                mu_strong = float(memberships.get('high_strong', 0.0))
                risk_raw = (0.5 * mu_slight) + (1.0 * mu_strong)
                risk_percent = round(self._clamp01(risk_raw) * 100.0, 1)
            else:
                risk_percent = self._risk_percent_max_type(memberships)

            status = self._status_from_risk_percent(risk_percent)

            parameter_results[user_key] = {
                'value': value, 'status': status,
                'risk_percent': risk_percent,
                'dominant_term': dominant_term, 'dominant_mu': dominant_mu,
                'memberships': memberships,
                'imputed': (user_key in imputed), 'regulated': True,
            }

        if imputed:
            msg += f" (หมายเหตุ: เติมค่าแทนสำหรับ: {', '.join(imputed)})"

        try:
            M = self._fuzzify_all(sim_inputs)
            rule_firing = self._rule_firing_report(M)
        except Exception:
            rule_firing = []

        return {
            'overall_score': score, 'overall_level': level,
            'band_by_score': level, 'overall_message': msg,
            'parameter_results': parameter_results,
            'fuzzy_membership': fuzzy_membership,
            'rule_firing': rule_firing,
            'parameters_used': used, 'parameters_imputed': imputed,
            'building_type': self.building_type,
        }


if __name__ == '__main__':
    print(f"=== WaterQualityFuzzySystem v{FUZZY_VERSION} self-test ===\n")
    excellent_case = {
        'pH': 7.0, 'BOD': 5, 'COD': 30, 'TSS': 10, 'TDS': 500,
        'O&G': 2.0, 'TKN': 10, 'Sulfide': 0.2, 'TCB': 1000, 'FCB': 200, 'Cl2': 0.3
    }
    print("Excellent test case:", excellent_case, "\n")
    for bt in BUILDING_TYPES:
        fz = get_fuzzy_system(bt)
        res = fz.evaluate_overall(excellent_case)
        unreg = [k for k, v in res['parameter_results'].items()
                 if v.get('regulated') is False]
        print(f"[ประเภท {bt}]  Score: {res['overall_score']}  Level: {res['overall_level']}")
        print(f"   ไม่กำหนด: {unreg if unreg else '—'}")
