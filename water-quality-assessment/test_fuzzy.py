# test_fuzzy.py — v2.1 verification suite
#
# ทดสอบความถูกต้องของระบบ Fuzzy หลังแก้ MF ใน v2.1:
# 1. ค่า x = S (ขีดผ่านพอดี) ต้องได้ μ(safe) = 1.0 (ไม่ใช่ μ(medium)=1.0)
# 2. คะแนนตาม WQI bands ใหม่ (Excellent 80+/Good 60+/Fair 40+/Poor 20+/Very Poor 0+)
# 3. ค่ามาตรฐานเดียวกัน → คะแนนเปลี่ยนตามประเภทอาคารถูกต้อง
# 4. พารามิเตอร์ "ไม่กำหนด" ต้องไม่ลดคะแนน
#
# วิธีรัน: python3 test_fuzzy.py

import skfuzzy as fuzz
from fuzzy_logic import (
    WaterQualityFuzzySystem, get_fuzzy_system,
    BUILDING_STANDARDS, score_to_wqi_band, FUZZY_VERSION
)

print(f"=== Test suite for fuzzy v{FUZZY_VERSION} ===\n")


def check_membership_at_S(bt='ก', param='BOD'):
    """ทดสอบ μ(safe) ที่ x = S ต้อง ≈ 1.0"""
    fs = get_fuzzy_system(bt)
    S = BUILDING_STANDARDS[bt][param]['max']
    var = getattr(fs, param if param != 'O&G' else 'OG')
    mu_safe   = fuzz.interp_membership(var.universe, var['safe'].mf, S)
    mu_medium = fuzz.interp_membership(var.universe, var['medium'].mf, S)
    return mu_safe, mu_medium, S


print("─" * 70)
print("TEST 1: μ(safe) ที่ x = S (ขีดผ่านพอดี)")
print("─" * 70)
print(f"{'อาคาร':6} {'พารามิเตอร์':12} {'S':>6} {'μ(safe)':>10} {'μ(medium)':>12} ผล")
print("─" * 70)
all_pass_t1 = True
for bt in ['ก','ข','ค','ง']:
    for param in ['BOD','COD','TSS','TKN']:
        if BUILDING_STANDARDS[bt][param] is None:
            continue
        s, m, S = check_membership_at_S(bt, param)
        ok = (s > 0.95) and (m < 0.5)
        if not ok: all_pass_t1 = False
        mark = '✅' if ok else '❌'
        print(f"  {bt}    {param:12} {S:>6} {s:>10.3f} {m:>12.3f}    {mark}")
print(f"\nสรุป Test 1: {'PASS ✅' if all_pass_t1 else 'FAIL ❌'}\n")


print("─" * 70)
print("TEST 2: WQI Score Bands — น้ำดี / กลาง / แย่")
print("─" * 70)

test_cases = [
    ("น้ำดีมาก (ครึ่งของ S)", 'ก',
     {'pH':7,'BOD':10,'COD':60,'TSS':15,'TDS':500,'O&G':5,'TKN':15,'Sulfide':0.3,'TCB':1000,'FCB':200,'Cl2':1.0},
     ['Good','Excellent']),
    ("น้ำ = ขีดผ่านพอดี (BOD=20=S)", 'ก',
     {'pH':7,'BOD':20,'COD':120,'TSS':30,'TDS':1000,'O&G':20,'TKN':35,'Sulfide':1.0,'TCB':5000,'FCB':1000,'Cl2':1.0},
     ['Good','Excellent']),
    ("น้ำเฉียดเกิน (1.2S)", 'ก',
     {'pH':7,'BOD':24,'COD':140,'TSS':36,'TDS':1200,'O&G':24,'TKN':42,'Sulfide':1.2,'TCB':6000,'FCB':1200,'Cl2':1.0},
     ['Fair','Good']),
    ("น้ำเกิน 1.5S (medium peak)", 'ก',
     {'pH':7,'BOD':30,'COD':180,'TSS':45,'TDS':1500,'O&G':30,'TKN':52,'Sulfide':1.5,'TCB':7500,'FCB':1500,'Cl2':1.0},
     ['Fair','Poor']),
    ("น้ำเกินมาก 2S", 'ก',
     {'pH':7,'BOD':40,'COD':240,'TSS':60,'TDS':2000,'O&G':40,'TKN':70,'Sulfide':2.0,'TCB':10000,'FCB':2000,'Cl2':1.0},
     ['Poor','Very Poor']),
    ("น้ำเลวร้าย (BOD=80, FCB=50000)", 'ก',
     {'pH':5.0,'BOD':80,'COD':400,'TSS':200,'TDS':3000,'O&G':50,'TKN':100,'Sulfide':3.0,'TCB':80000,'FCB':50000,'Cl2':0},
     ['Very Poor','Poor']),
]

all_pass_t2 = True
print(f"{'Test':45} {'Score':>7} {'Band':>10} ผล")
print("─" * 70)
for desc, bt, params, expected_bands in test_cases:
    ev = get_fuzzy_system(bt).evaluate_overall(params)
    score = ev['overall_score']
    band  = ev['overall_level']
    ok = band in expected_bands
    if not ok: all_pass_t2 = False
    mark = '✅' if ok else '❌'
    exp = '/'.join(expected_bands)
    print(f"  {desc:43} {score:>7.1f} {band:>10}   {mark}  (expect: {exp})")
print(f"\nสรุป Test 2: {'PASS ✅' if all_pass_t2 else 'FAIL ❌'}\n")


print("─" * 70)
print("TEST 3: คะแนนต่างกันตามประเภทอาคาร (S เข้ม → score ต่ำ)")
print("─" * 70)

test_params = {'pH':7,'BOD':28,'COD':100,'TSS':38,'TDS':900,'O&G':10,'TKN':32,
                'Sulfide':0.5,'TCB':3000,'FCB':800,'Cl2':1.0}
print(f"Input: BOD=28, TSS=38 (อยู่ระหว่าง S ของแต่ละประเภท)")
print(f"คาดหวัง: ก เกิน → score ต่ำ, ข เฉียด, ค/ง ผ่าน (score สูงขึ้น)\n")
print(f"{'อาคาร':10} {'S_BOD':>8} {'S_TSS':>8} {'Score':>10} {'Band':>12}")
print("─" * 60)
scores = []
for bt in ['ก','ข','ค','ง']:
    ev = get_fuzzy_system(bt).evaluate_overall(test_params)
    s_bod = BUILDING_STANDARDS[bt]['BOD']['max']
    s_tss = BUILDING_STANDARDS[bt]['TSS']['max']
    score = ev['overall_score']
    scores.append(score)
    print(f"  {bt:10} {s_bod:>8} {s_tss:>8} {score:>10.1f} {ev['overall_level']:>12}")

monotonic = scores[0] <= scores[1] <= scores[2] <= scores[3]
print(f"\nMonotonic (ก ≤ ข ≤ ค ≤ ง): {'✅ PASS' if monotonic else '❌ FAIL'}\n")


print("─" * 70)
print("TEST 4: พารามิเตอร์ 'ไม่กำหนด' ต้องไม่ลดคะแนน")
print("─" * 70)

test_unreg = {'pH':7,'BOD':40,'COD':100,'TSS':50,
               'TDS':10000, 'O&G':15, 'TKN':500,
               'Sulfide':5, 'TCB':100000, 'FCB':30000, 'Cl2':0.5}

print(f"ง: ตั้ง TDS/TKN/Sulfide/TCB/FCB สูงเกินไกล แต่ regulated params (BOD/TSS) ผ่าน")
ev_ง = get_fuzzy_system('ง').evaluate_overall(test_unreg)
print(f"  Score = {ev_ง['overall_score']:.1f}")
print(f"  Band  = {ev_ง['overall_level']}")
pr = ev_ง['parameter_results']
print(f"  TKN status:   {pr.get('TKN',{}).get('status')}")
print(f"  Sulfide:      {pr.get('Sulfide',{}).get('status')}")
print(f"  FCB:          {pr.get('FCB',{}).get('status')}")
print(f"  BOD risk:     {pr.get('BOD',{}).get('risk_percent')}")

unreg_ignored = ev_ง['overall_score'] >= 40   # ≥ Fair (BOD/TSS=S → เฉียดผ่าน)
print(f"\n→ คะแนน ≥ 40 (Fair+): {'✅ PASS' if unreg_ignored else '❌ FAIL'}")
print(f"  หมายเหตุ: BOD/TSS ตั้งที่ S พอดี → score คาดว่าอยู่ระหว่าง Fair-Good (40-79)")
print(f"  เป้าหมายหลักของ test นี้: unregulated params ที่สูงมาก *ไม่ทำให้ score ตกไป Poor*\n")


print("─" * 70)
print("TEST 5: ความ smooth ของ MF (ไม่มี gap ที่ทุก term = 0)")
print("─" * 70)

fs = get_fuzzy_system('ก')
gap_found = False
for v in range(0, 80):
    total = 0
    for term in ['safe','low','medium','high']:
        total += fuzz.interp_membership(fs.BOD.universe, fs.BOD[term].mf, float(v))
    if total < 0.5:
        print(f"  ⚠️ Gap at BOD={v}: total μ = {total:.3f}")
        gap_found = True

if not gap_found:
    print("  ✅ ไม่มี gap — ทุกค่า x มี membership รวม ≥ 0.5")
print()


print("═" * 70)
all_tests = all_pass_t1 and all_pass_t2 and monotonic and unreg_ignored and not gap_found
print(f"  ผลรวม: {'✅ ผ่านทั้งหมด' if all_tests else '❌ มีบาง test ที่ไม่ผ่าน'}")
print("═" * 70)
