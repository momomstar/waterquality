import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
import json


class WaterQualityFuzzySystem:
    """
    Pure Mamdani Fuzzy Logic System (Knowledge-based) - 5 Levels with Overlap (CALIBRATED)

    Target score bands:
      90–100  Excellent
      70–89   Good
      50–69   Fair
      25–49   Poor
      0–24    Very Poor

    Reporting:
      ✅ Per-parameter report uses "Fuzzy Risk Index (%)"
         Risk = μ(medium)*0.5 + μ(high)*1.0 + μ(very_high)*1.2  (normalize to 0–100%)
      ✅ Status per parameter:
         risk < 20 => Pass, risk < 50 => Near Limit, else Fail
    """

    def __init__(self):
        # ===== Standards (S) =====
        self.standards = {
            'pH': {'min': 5.5, 'max': 9.0},
            'BOD': {'max': 20},
            'COD': {'max': 120},
            'TSS': {'max': 50},
            'TDS': {'max': 3000},
            'O&G': {'max': 5},
            'TKN': {'max': 100},
            'Sulfide': {'max': 1},
            'TCB': {'max': 20000},
            'FCB': {'max': 4000},
            'Cl2': {'min': 0.2, 'max': 5},
        }

        # ===== Default band ratios for max-type =====
        self.delta0_default = 0.10
        self.delta1_default = 0.10
        self.delta2 = {
            'BOD': 1.0, 'COD': 1.0, 'TSS': 1.0, 'O&G': 1.0, 'TKN': 1.0,
            'Sulfide': 1.0,
            'FCB': 1.5, 'TCB': 1.5,
            'TDS': 2.0,
        }

        # ===== Safety margin design =====
        self.safe_start_ratio = 0.70
        self.safe_end_ratio = 0.90

        self._build_fuzzy_system()

    # ============================================================
    # Utils
    # ============================================================
    @staticmethod
    def _clamp(v, vmin, vmax):
        try:
            x = float(v)
        except Exception:
            return float(vmin)
        if x < vmin:
            return float(vmin)
        if x > vmax:
            return float(vmax)
        return x

    @staticmethod
    def _clamp01(x):
        try:
            x = float(x)
        except Exception:
            return 0.0
        if x < 0.0:
            return 0.0
        if x > 1.0:
            return 1.0
        return x

    # ============================================================
    # Risk Index helpers (REPORT ONLY)
    # ============================================================
    def _risk_percent_max_type(self, memberships: dict) -> float:
        mu_med = float(memberships.get('medium', 0.0))
        mu_high = float(memberships.get('high', 0.0))
        mu_vhigh = float(memberships.get('very_high', 0.0))
        risk_raw = (0.5 * mu_med) + (1.0 * mu_high) + (1.2 * mu_vhigh)
        risk_norm = self._clamp01(risk_raw / 1.2)
        return round(risk_norm * 100.0, 1)

    def _risk_percent_ph(self, memberships: dict) -> float:
        mu_slight = max(
            float(memberships.get('acidic_slight', 0.0)),
            float(memberships.get('alkaline_slight', 0.0))
        )
        mu_strong = max(
            float(memberships.get('acidic_strong', 0.0)),
            float(memberships.get('alkaline_strong', 0.0))
        )
        risk_raw = (0.5 * mu_slight) + (1.0 * mu_strong)
        return round(self._clamp01(risk_raw) * 100.0, 1)

    def _risk_percent_cl2(self, memberships: dict) -> float:
        mu_slight = max(
            float(memberships.get('low_slight', 0.0)),
            float(memberships.get('high_slight', 0.0))
        )
        mu_strong = max(
            float(memberships.get('low_strong', 0.0)),
            float(memberships.get('high_strong', 0.0))
        )
        risk_raw = (0.5 * mu_slight) + (1.0 * mu_strong)
        return round(self._clamp01(risk_raw) * 100.0, 1)

    @staticmethod
    def _status_from_risk_percent(risk_percent: float) -> str:
        r = float(risk_percent)
        if r < 20:
            return 'Pass'
        if r < 50:
            return 'Near Limit'
        return 'Fail'

    # ============================================================
    # Membership builders (max-type): safe / low / medium / high (+ very_high for coliform)
    # ============================================================
    def _make_low_medium_high(self, var, param_name, delta0=None, delta1=None, delta2=None):
        """
        max-type (ยิ่งมากยิ่งแย่)

        safe   = trap [u_min,u_min, 0.70S, 0.90S]
        low    = trap [u_min,u_min, a, b]
        medium = tri  [a, b, c]
        high   = trap [b, c, d, d]

        for coliform:
          very_high = trap [d, d, u_max, u_max]
        """
        S = float(self.standards[param_name]['max'])

        d0 = self.delta0_default if delta0 is None else float(delta0)
        d1 = self.delta1_default if delta1 is None else float(delta1)
        d2 = self.delta2.get(param_name, 1.0) if delta2 is None else float(delta2)

        a = S * (1.0 - d0)
        b = S
        c = S * (1.0 + d1)
        d = S * (1.0 + d2)

        u_min = float(var.universe.min())
        u_max = float(var.universe.max())
        d = min(d, u_max)

        a = max(u_min, min(a, b))
        c = max(b, c)
        d = max(c, d)

        safe_start = S * float(self.safe_start_ratio)
        safe_end = S * float(self.safe_end_ratio)
        safe_start = max(u_min, min(safe_start, safe_end))
        safe_end = max(safe_start, min(safe_end, u_max))
        var['safe'] = fuzz.trapmf(var.universe, [u_min, u_min, safe_start, safe_end])

        var['low'] = fuzz.trapmf(var.universe, [u_min, u_min, a, b])
        var['medium'] = fuzz.trimf(var.universe, [a, b, c])
        var['high'] = fuzz.trapmf(var.universe, [b, c, d, d])

        if param_name in ('TCB', 'FCB'):
            var['very_high'] = fuzz.trapmf(var.universe, [d, d, u_max, u_max])

    def _make_sulfide_mf_fixed(self, var):
        """
        Sulfide FIX + safe:
          safe   : <=0.8 (clear margin)
          low    : <=1.0 (pass)
          medium : near 1.0
          high   : >1.0
        """
        u_min = float(var.universe.min())
        u_max = float(var.universe.max())

        var['safe'] = fuzz.trapmf(var.universe, [0.0, 0.0, 0.6, 0.8])

        low = [0.0, 0.0, 0.9, 1.0]
        med = [0.9, 1.0, 1.2]
        high = [1.0, 1.2, 2.0, 2.0]

        low = [self._clamp(x, u_min, u_max) for x in low]
        med = [self._clamp(x, u_min, u_max) for x in med]
        high = [self._clamp(x, u_min, u_max) for x in high]

        var['low'] = fuzz.trapmf(var.universe, low)
        var['medium'] = fuzz.trimf(var.universe, med)
        var['high'] = fuzz.trapmf(var.universe, high)

    # ============================================================
    # Build Fuzzy System
    # ============================================================
    def _build_fuzzy_system(self):
        # ==================== Antecedents ====================
        self.pH = ctrl.Antecedent(np.arange(0, 14.1, 0.1), 'pH')
        self.BOD = ctrl.Antecedent(np.arange(0, 201, 0.1), 'BOD')
        self.COD = ctrl.Antecedent(np.arange(0, 1001, 1), 'COD')
        self.TSS = ctrl.Antecedent(np.arange(0, 501, 0.1), 'TSS')
        self.TDS = ctrl.Antecedent(np.arange(0, 20001, 1), 'TDS')
        self.OG = ctrl.Antecedent(np.arange(0, 101, 0.1), 'OG')
        self.TKN = ctrl.Antecedent(np.arange(0, 501, 1), 'TKN')
        self.Sulfide = ctrl.Antecedent(np.arange(0, 10.1, 0.01), 'Sulfide')
        self.TCB = ctrl.Antecedent(np.arange(0, 100001, 1), 'TCB')
        self.FCB = ctrl.Antecedent(np.arange(0, 50001, 1), 'FCB')
        self.Cl2 = ctrl.Antecedent(np.arange(0, 10.1, 0.1), 'Cl2')

        # ==================== Consequent ====================
        self.Quality = ctrl.Consequent(np.arange(0, 101, 1), 'Quality')

        # ==================== Input Membership functions ====================
        # pH
        self.pH['acidic_strong'] = fuzz.trapmf(self.pH.universe, [0.0, 0.0, 5.0, 5.4])
        self.pH['acidic_slight'] = fuzz.trapmf(self.pH.universe, [5.2, 5.5, 5.7, 6.0])
        self.pH['neutral_core'] = fuzz.trapmf(self.pH.universe, [5.7, 6.2, 8.3, 8.7])
        self.pH['alkaline_slight'] = fuzz.trapmf(self.pH.universe, [8.5, 8.8, 9.0, 9.2])
        self.pH['alkaline_strong'] = fuzz.trapmf(self.pH.universe, [9.0, 9.4, 14.0, 14.0])

        # max-type via S,delta + safe (+ very_high for coliform)
        self._make_low_medium_high(self.BOD, 'BOD')
        self._make_low_medium_high(self.COD, 'COD')
        self._make_low_medium_high(self.TSS, 'TSS')
        self._make_low_medium_high(self.TDS, 'TDS')
        self._make_low_medium_high(self.OG, 'O&G')
        self._make_low_medium_high(self.TKN, 'TKN')
        self._make_low_medium_high(self.TCB, 'TCB')
        self._make_low_medium_high(self.FCB, 'FCB')

        # Sulfide FIX + safe
        self._make_sulfide_mf_fixed(self.Sulfide)

        # Cl2
        self.Cl2['low_strong'] = fuzz.trapmf(self.Cl2.universe, [0.0, 0.0, 0.05, 0.15])
        self.Cl2['low_slight'] = fuzz.trapmf(self.Cl2.universe, [0.10, 0.18, 0.25, 0.35])
        self.Cl2['normal_core'] = fuzz.trapmf(self.Cl2.universe, [0.30, 0.80, 4.0, 4.8])
        self.Cl2['high_slight'] = fuzz.trapmf(self.Cl2.universe, [4.7, 5.0, 5.2, 5.6])
        self.Cl2['high_strong'] = fuzz.trapmf(self.Cl2.universe, [5.3, 6.0, 10.0, 10.0])

        # ==================== Output MF (5 levels, overlap) ====================
        y = self.Quality.universe
        self.Quality['very_poor'] = fuzz.trapmf(y, [0, 0, 12, 22])
        self.Quality['poor'] = fuzz.trapmf(y, [20, 28, 42, 52])
        self.Quality['fair'] = fuzz.trapmf(y, [50, 55, 65, 70])
        self.Quality['good'] = fuzz.trapmf(y, [70, 78, 88, 92])
        self.Quality['excellent'] = fuzz.trapmf(y, [90, 95, 100, 100])

        # ==================== Rule base ====================
        self.rules_meta = []
        rules = []

        AND = lambda *xs: min(xs) if xs else 0.0
        OR = lambda *xs: max(xs) if xs else 0.0

        def add_rule(name, antecedent_expr, consequent_term, strength_fn):
            rules.append(ctrl.Rule(antecedent_expr, consequent_term))
            self.rules_meta.append({
                'name': name,
                'consequent': consequent_term.label,
                'strength_fn': strength_fn
            })

        # ---------------------------------------------------
        # EXCELLENT / GOOD gating
        # ---------------------------------------------------
        excellent_condition = (
            self.pH['neutral_core'] &
            self.Cl2['normal_core'] &
            self.BOD['safe'] & self.COD['safe'] & self.TSS['safe'] &
            self.Sulfide['safe'] &
            self.TCB['safe'] & self.FCB['safe'] &
            self.TKN['safe'] & self.OG['safe']
        )

        add_rule(
            "EXCELLENT: critical SAFE + pH neutral_core + Cl2 normal_core",
            excellent_condition,
            self.Quality['excellent'],
            lambda M: AND(
                M['pH']['neutral_core'], M['Cl2']['normal_core'],
                M['BOD']['safe'], M['COD']['safe'], M['TSS']['safe'],
                M['Sulfide']['safe'], M['TCB']['safe'], M['FCB']['safe'],
                M['TKN']['safe'], M['OG']['safe']
            )
        )

        add_rule(
            "GOOD: SAFE on critical + pH neutral_core + Cl2 normal_core (NOT excellent)",
            (
                self.pH['neutral_core'] &
                self.Cl2['normal_core'] &
                self.BOD['safe'] & self.COD['safe'] & self.TSS['safe'] &
                (self.Sulfide['safe'] | self.Sulfide['low']) &
                (self.TCB['safe'] | self.TCB['low']) &
                (self.FCB['safe'] | self.FCB['low']) &
                (self.TKN['safe'] | self.TKN['low'] | self.TKN['medium']) &
                (self.OG['safe'] | self.OG['low'] | self.OG['medium']) &
                ~(excellent_condition)
            ),
            self.Quality['good'],
            lambda M: AND(
                M['pH']['neutral_core'], M['Cl2']['normal_core'],
                M['BOD']['safe'], M['COD']['safe'], M['TSS']['safe'],
                OR(M['Sulfide']['safe'], M['Sulfide']['low']),
                OR(M['TCB']['safe'], M['TCB']['low']),
                OR(M['FCB']['safe'], M['FCB']['low']),
                OR(M['TKN']['safe'], M['TKN']['low'], M['TKN']['medium']),
                OR(M['OG']['safe'], M['OG']['low'], M['OG']['medium']),
                (1.0 - AND(
                    M['pH']['neutral_core'], M['Cl2']['normal_core'],
                    M['BOD']['safe'], M['COD']['safe'], M['TSS']['safe'],
                    M['Sulfide']['safe'], M['TCB']['safe'], M['FCB']['safe'],
                    M['TKN']['safe'], M['OG']['safe']
                ))
            )
        )

        # ---------------------------------------------------
        # FAIR
        # ---------------------------------------------------
        any_medium = (
            self.BOD['medium'] | self.COD['medium'] | self.TSS['medium'] | self.TKN['medium'] |
            self.OG['medium'] | self.TDS['medium'] | self.Sulfide['medium'] | self.FCB['medium'] | self.TCB['medium']
        )

        slight_abnormal = (
            self.pH['acidic_slight'] | self.pH['alkaline_slight'] |
            self.Cl2['low_slight'] | self.Cl2['high_slight']
        )

        add_rule(
            "FAIR: near-limit OR slight pH/Cl2 abnormal (no high, not severe)",
            (
                (self.pH['neutral_core'] & self.Cl2['normal_core'] & any_medium) |
                (slight_abnormal)
            ),
            self.Quality['fair'],
            lambda M: OR(
                AND(
                    M['pH']['neutral_core'], M['Cl2']['normal_core'],
                    OR(
                        M['BOD']['medium'], M['COD']['medium'], M['TSS']['medium'], M['TKN']['medium'],
                        M['OG']['medium'], M['TDS']['medium'], M['Sulfide']['medium'],
                        M['FCB']['medium'], M['TCB']['medium']
                    )
                ),
                OR(
                    M['pH']['acidic_slight'], M['pH']['alkaline_slight'],
                    M['Cl2']['low_slight'], M['Cl2']['high_slight']
                )
            )
        )

        # ---------------------------------------------------
        # POOR
        # ---------------------------------------------------
        any_high = (
            self.BOD['high'] | self.COD['high'] | self.TSS['high'] | self.TDS['high'] |
            self.TKN['high'] | self.OG['high'] | self.Sulfide['high'] | self.FCB['high'] | self.TCB['high']
        )

        add_rule(
            "POOR: any pollutant high (but not severe)",
            any_high,
            self.Quality['poor'],
            lambda M: OR(
                M['BOD']['high'], M['COD']['high'], M['TSS']['high'], M['TDS']['high'],
                M['TKN']['high'], M['OG']['high'], M['Sulfide']['high'], M['FCB']['high'], M['TCB']['high']
            )
        )

        add_rule(
            "POOR: strong pH/Cl2 abnormal",
            (self.pH['acidic_strong'] | self.pH['alkaline_strong'] | self.Cl2['low_strong'] | self.Cl2['high_strong']),
            self.Quality['poor'],
            lambda M: OR(
                M['pH']['acidic_strong'], M['pH']['alkaline_strong'],
                M['Cl2']['low_strong'], M['Cl2']['high_strong']
            )
        )

        # ---------------------------------------------------
        # VERY POOR (tuned)
        # ---------------------------------------------------
        both_coliform_very_high = (self.FCB['very_high'] & self.TCB['very_high'])

        strong_abnormal = (
            self.pH['acidic_strong'] | self.pH['alkaline_strong'] |
            self.Cl2['low_strong'] | self.Cl2['high_strong']
        )

        severe_combo3 = (
            self.BOD['high'] &
            self.COD['high'] &
            (self.TSS['high'] | self.TDS['high'] | self.TKN['high'])
        )

        add_rule(
            "VERY POOR: (FCB&TCB very_high) OR (strong abnormal + severe_combo3)",
            (both_coliform_very_high | (strong_abnormal & severe_combo3)),
            self.Quality['very_poor'],
            lambda M: OR(
                AND(M['FCB'].get('very_high', 0.0), M['TCB'].get('very_high', 0.0)),
                AND(
                    OR(M['pH']['acidic_strong'], M['pH']['alkaline_strong'],
                       M['Cl2']['low_strong'], M['Cl2']['high_strong']),
                    AND(
                        M['BOD']['high'],
                        M['COD']['high'],
                        OR(M['TSS']['high'], M['TDS']['high'], M['TKN']['high'])
                    )
                )
            )
        )

        add_rule(
            "POOR: O&G high (reinforce)",
            self.OG['high'],
            self.Quality['poor'],
            lambda M: M['OG']['high']
        )

        self.control_system = ctrl.ControlSystem(rules)

    # ============================================================
    # Impute neutral values
    # ============================================================
    def _impute_neutral(self, user_key):
        if user_key == 'pH':
            mn = self.standards['pH']['min']
            mx = self.standards['pH']['max']
            return (mn + mx) / 2.0
        if user_key == 'Cl2':
            mn = self.standards['Cl2']['min']
            mx = self.standards['Cl2']['max']
            return (mn + mx) / 2.0
        if user_key in self.standards and 'max' in self.standards[user_key]:
            return float(self.standards[user_key]['max'])
        return 0.0

    # ============================================================
    # Fuzzify all inputs (for rule firing + membership report)
    # ============================================================
    def _fuzzify_all(self, sim_inputs):
        mapping = {
            'pH': self.pH, 'BOD': self.BOD, 'COD': self.COD, 'TSS': self.TSS, 'TDS': self.TDS,
            'OG': self.OG, 'TKN': self.TKN, 'Sulfide': self.Sulfide, 'TCB': self.TCB,
            'FCB': self.FCB, 'Cl2': self.Cl2
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
                    'rule': r['name'],
                    'consequent': r['consequent'],
                    'strength': round(s, 4)
                })
        fired.sort(key=lambda x: x['strength'], reverse=True)
        return fired[:top_k]

    # ============================================================
    # Evaluation
    # ============================================================
    def evaluate_overall(self, parameters: dict):
        param_mapping = {
            'pH': 'pH',
            'BOD': 'BOD',
            'COD': 'COD',
            'TSS': 'TSS',
            'TDS': 'TDS',
            'O&G': 'OG',
            'TKN': 'TKN',
            'Sulfide': 'Sulfide',
            'TCB': 'TCB',
            'FCB': 'FCB',
            'Cl2': 'Cl2',
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
                'overall_score': None,
                'overall_level': 'No Data',
                'band_by_score': 'No Data',
                'overall_message': f'Fuzzy computation error: {e}',
                'parameter_results': {},
                'fuzzy_membership': {},
                'rule_firing': [],
                'parameters_used': used,
                'parameters_imputed': imputed,
            }

        # score -> level
        if score >= 90:
            level = 'Excellent'
            msg = 'คุณภาพน้ำดีเยี่ยม ✅✅'
        elif score >= 70:
            level = 'Good'
            msg = 'คุณภาพน้ำอยู่ในเกณฑ์ดี ✅'
        elif score >= 50:
            level = 'Fair'
            msg = 'คุณภาพน้ำพอใช้ ควรเฝ้าระวัง ⚠️'
        elif score >= 25:
            level = 'Poor'
            msg = 'คุณภาพน้ำไม่ดี ควรปรับปรุงระบบบำบัด ❌'
        else:
            level = 'Very Poor'
            msg = 'คุณภาพน้ำแย่มาก อันตราย/ควรแก้ไขเร่งด่วน ❌❌'

        # band_by_score
        if score is None:
            band_by_score = 'No Data'
        elif score >= 90:
            band_by_score = 'Excellent'
        elif score >= 70:
            band_by_score = 'Good'
        elif score >= 50:
            band_by_score = 'Fair'
        elif score >= 25:
            band_by_score = 'Poor'
        else:
            band_by_score = 'Very Poor'

        # membership report
        fuzzy_membership = {}
        for fuzzy_key, v in sim_inputs.items():
            try:
                var = getattr(self, fuzzy_key)
                memberships = {}
                for term in var.terms:
                    memberships[term] = round(
                        float(fuzz.interp_membership(var.universe, var[term].mf, v)),
                        3
                    )
                fuzzy_membership[fuzzy_key] = {'value': v, 'memberships': memberships}
            except Exception:
                pass

        reverse_mapping = {v: k for k, v in param_mapping.items()}
        parameter_results = {}

        # ✅ NEW: risk-based per-parameter reporting (risk_percent always present)
        for fuzzy_key, data in fuzzy_membership.items():
            user_key = reverse_mapping.get(fuzzy_key, fuzzy_key)
            memberships = data.get('memberships', {}) or {}
            value = data.get('value', None)

            if not memberships:
                continue

            dominant_term = max(memberships, key=memberships.get)
            dominant_mu = round(float(memberships[dominant_term]), 3)

            if fuzzy_key == 'pH':
                risk_percent = self._risk_percent_ph(memberships)
            elif fuzzy_key == 'Cl2':
                risk_percent = self._risk_percent_cl2(memberships)
            else:
                risk_percent = self._risk_percent_max_type(memberships)

            status = self._status_from_risk_percent(risk_percent)

            parameter_results[user_key] = {
                'value': value,
                'status': status,
                'risk_percent': risk_percent,
                'dominant_term': dominant_term,
                'dominant_mu': dominant_mu,
                'memberships': memberships,
                'imputed': (user_key in imputed)
            }

        if imputed:
            msg += f" (หมายเหตุ: เติมค่าแทนสำหรับ: {', '.join(imputed)})"

        try:
            M = self._fuzzify_all(sim_inputs)
            rule_firing = self._rule_firing_report(M)
        except Exception:
            rule_firing = []

        return {
            'overall_score': score,
            'overall_level': level,
            'band_by_score': band_by_score,
            'overall_message': msg,
            'parameter_results': parameter_results,
            'fuzzy_membership': fuzzy_membership,
            'rule_firing': rule_firing,
            'parameters_used': used,
            'parameters_imputed': imputed,
        }

    def _validate_inputs(self, parameters: dict):
        """
        Validate input parameters to ensure they are within the acceptable range.
        """
        for key, value in parameters.items():
            if key in self.standards:
                min_val = self.standards[key].get('min', float('-inf'))
                max_val = self.standards[key].get('max', float('inf'))
                if not (min_val <= value <= max_val):
                    raise ValueError(f"Parameter '{key}' with value {value} is out of range ({min_val}–{max_val}).")

    def save_results_to_file(self, results: dict, filename: str = "results.json"):
        """
        Save the evaluation results to a JSON file.
        """
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4)


if __name__ == '__main__':
    fuzzy = WaterQualityFuzzySystem()

    case = {
        'pH': 6.0, 'BOD': 19, 'COD': 111, 'TSS': 45, 'TDS': 2700,
        'O&G': 4.0, 'TKN': 90, 'Sulfide': 0.9, 'TCB': 19000, 'FCB': 3500, 'Cl2': 3.0
    }

    try:
        # Validate inputs before evaluation
        fuzzy._validate_inputs(case)

        # Evaluate the case
        res = fuzzy.evaluate_overall(case)

        # Print results
        print("overall_score:", res['overall_score'])
        print("overall_level:", res['overall_level'])
        print("band_by_score:", res.get('band_by_score'))
        print("example per-parameter risk (TDS):", res["parameter_results"].get("TDS", {}))
        print("rule_firing:")
        for r in res.get('rule_firing', []):
            print("-", r)

        # Save results to a file
        fuzzy.save_results_to_file(res, "water_quality_results.json")

    except ValueError as e:
        print(f"Input validation error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
