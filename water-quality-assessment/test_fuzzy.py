# test_fuzzy.py
from pprint import pprint
import skfuzzy as fuzz

from fuzzy_logic import WaterQualityFuzzySystem


def interp_term(antecedent, term_name, x):
    mf = antecedent[term_name].mf
    return float(fuzz.interp_membership(antecedent.universe, mf, x))


def summarize_memberships(system, sample, topk=2, min_mu=0.2):
    summaries = {}

    attr_map = {'O&G': 'OG', 'Sulfide': 'Sulfide', 'Cl2': 'Cl2'}

    # ถ้าคะแนนเท่ากัน ให้เรียงลำดับความสำคัญแบบนี้
    prefer_order = {
        'safe': 0, 'low': 1, 'medium': 2, 'high': 3, 'very_high': 4,
        'neutral_core': 0,
        'acidic_slight': 1, 'alkaline_slight': 1,
        'acidic_strong': 2, 'alkaline_strong': 2,
        'normal_core': 0,
        'low_slight': 1, 'high_slight': 1,
        'low_strong': 2, 'high_strong': 2,
    }

    for key, x in sample.items():
        sys_attr = attr_map.get(key, key)
        if not hasattr(system, sys_attr):
            continue

        ant = getattr(system, sys_attr)
        terms = list(ant.terms.keys())

        scored = []
        for t in terms:
            mu = interp_term(ant, t, x)
            scored.append((t, mu))

        # sort by mu desc, then preference asc
        scored.sort(key=lambda z: (-z[1], prefer_order.get(z[0], 99)))

        # ✅ เอาแค่ 1 term หลักพอ (อ่านง่าย)
        t, mu = scored[0]
        if mu >= min_mu:
            summaries[key] = [(t, round(mu, 3))]

    return summaries



def run_case(name, fs, sample, expected_level=None):
    print("=" * 70)
    print(f"[{name}]")
    print("Input:", sample)

    # ✅ correct method name for your system
    result = fs.evaluate_overall(sample)

    overall_score = result.get("overall_score")
    overall_level = result.get("overall_level")
    overall_message = result.get("overall_message")
    rule_firing = result.get("rule_firing", [])

    print(f"overall_score: {overall_score} | overall_level: {overall_level}")
    print("message:", overall_message)

    # ✅ membership summary
    ms = summarize_memberships(fs, sample, topk=2, min_mu=0.2)
    if ms:
        print("\nmembership_summary(top terms):")
        pprint(ms, sort_dicts=False)

    # ✅ rule firing
    if rule_firing:
        print("\nrule_firing:")
        for r in rule_firing:
            print(" -", r)

    if expected_level is not None:
        ok = (overall_level == expected_level)
        print(f"\n[CHECK] {name}: expected={expected_level}, got={overall_level} -> {'PASS ✅' if ok else 'FAIL ❌'}")


# ---------- test cases ----------
EXCELLENT_CASE = {
    'pH': 7.0, 'BOD': 10, 'COD': 60, 'TSS': 25, 'TDS': 1500, 'O&G': 2.0,
    'TKN': 50, 'Sulfide': 0.3, 'TCB': 8000, 'FCB': 1500, 'Cl2': 2.0
}

GOOD_CASE = {
    'pH': 6.8, 'BOD': 15, 'COD': 90, 'TSS': 30, 'TDS': 1800, 'O&G': 2.5,
    'TKN': 70, 'Sulfide': 0.4, 'TCB': 12000, 'FCB': 2500, 'Cl2': 2.0
}

FAIR_CASE = {
    'pH': 6.5, 'BOD': 20, 'COD': 120, 'TSS': 50, 'TDS': 2500, 'O&G': 5.0,
    'TKN': 100, 'Sulfide': 1.0, 'TCB': 20000, 'FCB': 4000, 'Cl2': 2.0
}

POOR_CASE = {
    'pH': 6.0, 'BOD': 35, 'COD': 160, 'TSS': 80, 'TDS': 3200, 'O&G': 8.0,
    'TKN': 130, 'Sulfide': 1.4, 'TCB': 30000, 'FCB': 8000, 'Cl2': 4.5
}

VERY_POOR_CASE = {
    'pH': 5.0, 'BOD': 60, 'COD': 300, 'TSS': 200, 'TDS': 5000, 'O&G': 20.0,
    'TKN': 250, 'Sulfide': 3.0, 'TCB': 90000, 'FCB': 45000, 'Cl2': 8.0
}

# ✅ new case: coliform very_high ทั้งคู่ แต่ตัวอื่นดี
VERY_POOR_coliform_only = {
    'pH': 7.0,'BOD':10,'COD':60,'TSS':25,'TDS':1500,'O&G':2,'TKN':50,'Sulfide':0.3,
    'TCB': 90000,'FCB': 45000,'Cl2':2.0
}


def main():
    fs = WaterQualityFuzzySystem()

    run_case("EXCELLENT_CASE", fs, EXCELLENT_CASE, expected_level="Excellent")
    run_case("GOOD_CASE", fs, GOOD_CASE, expected_level="Good")
    run_case("FAIR_CASE", fs, FAIR_CASE, expected_level="Fair")
    run_case("POOR_CASE", fs, POOR_CASE, expected_level="Poor")
    run_case("VERY_POOR_CASE", fs, VERY_POOR_CASE, expected_level="Very Poor")
    run_case("VERY_POOR_coliform_only", fs, VERY_POOR_coliform_only, expected_level="Very Poor")


if __name__ == "__main__":
    main()
