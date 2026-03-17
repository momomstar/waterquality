"""
Main Flask Application - Enhanced Dashboard with Detailed Statistics
ไฟล์ Python สำหรับ Backend (ไม่มี HTML/CSS)
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
import os
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
import math

from config import config
from models import db, User, WaterQualityData, EvaluationResult, init_db
from fuzzy_logic import WaterQualityFuzzySystem
from types import SimpleNamespace

# ====== CONST ======
REQUIRED_FUZZY_COLS = ['pH', 'BOD', 'COD', 'TSS', 'TDS', 'O&G', 'TKN', 'Sulfide', 'TCB', 'FCB', 'Cl2']

# ====== APP INIT ======
app = Flask(__name__)
app.config.from_object(config['development'])

init_db(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'กรุณาเข้าสู่ระบบก่อนใช้งาน'

# ✅ ใช้ instance เดียว (เร็ว+ชัวร์)
fuzzy_system = WaterQualityFuzzySystem()


# =========================
# HELPERS (GLOBAL)
# =========================
def is_missing(x):
    if x is None:
        return True
    if isinstance(x, str) and x.strip() == '':
        return True
    try:
        return pd.isna(x)
    except Exception:
        return False


def safe_float(x):
    """Convert x to float safely. Return None for None/''/NaN/inf/invalid."""
    try:
        if x is None:
            return None
        if isinstance(x, str):
            x = x.strip()
            if x == '':
                return None
        val = float(x)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    except Exception:
        return None


def to_object(data):
    """
    Recursively convert dict to object (SimpleNamespace)
    ใช้เพื่อให้ Jinja เรียกด้วย .score .status ได้
    """
    if isinstance(data, dict):
        return SimpleNamespace(**{k: to_object(v) for k, v in data.items()})
    if isinstance(data, list):
        return [to_object(item) for item in data]
    return data


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_float(form, name):
    """Safely convert form input to float. Return None if missing/empty."""
    value = form.get(name)
    return float(value) if value not in (None, '') else None


def normalize_key(k: str) -> str:
    return (k or "").replace('&', '').replace(' ', '').replace('_', '').lower().strip()


def score_to_overall_status(score):
    """
    ✅ NEW MAPPING (ตามที่คุณสรุปไว้):
      90–100 Pass (Excellent)
      70–89  Pass (Good)
      50–69  Near Limit (Fair)
      0–49   Fail (Poor/Very Poor)

    หมายเหตุ: UI ใช้แค่ Pass/Near Limit/Fail
    """
    if score is None:
        return 'No Data'
    try:
        s = float(score)
    except Exception:
        return 'No Data'

    if s >= 70:
        return 'Pass'
    elif s >= 50:
        return 'Near Limit'
    else:
        return 'Fail'


# =========================
# WATER STANDARDS (SINGLE SOURCE OF TRUTH)
# =========================
WATER_STANDARDS = {}
for param_name, standard in fuzzy_system.standards.items():
    param_display_names = {
        'pH': 'ค่าความเป็นกรด-ด่าง',
        'BOD': 'ความต้องการออกซิเจนทางชีวภาพ',
        'COD': 'ความต้องการออกซิเจนทางเคมี',
        'TSS': 'ของแข็งแขวนลอยทั้งหมด',
        'TDS': 'ของแข็งละลายทั้งหมด',
        'O&G': 'น้ำมันและไขมัน',
        'TKN': 'ไนโตรเจนรวม',
        'Sulfide': 'ซัลไฟด์',
        'TCB': 'โคลิฟอร์มทั้งหมด',
        'FCB': 'โคลิฟอร์มอุจจาระ',
        'Cl2': 'คลอรีนตกค้าง'
    }

    param_units = {
        'pH': '',
        'BOD': 'mg/L',
        'COD': 'mg/L',
        'TSS': 'mg/L',
        'TDS': 'mg/L',
        'O&G': 'mg/L',
        'TKN': 'mg/L',
        'Sulfide': 'mg/L',
        'TCB': 'MPN/100mL',
        'FCB': 'MPN/100mL',
        'Cl2': 'mg/L'
    }

    # ✅ type ให้ครบ: range หรือ max
    if standard.get('min') is not None and standard.get('max') is not None:
        std_type = 'range'
        std_min = standard.get('min')
        std_max = standard.get('max')
    elif standard.get('max') is not None:
        std_type = 'max'
        std_min = None
        std_max = standard.get('max')
    else:
        std_type = None
        std_min = standard.get('min')
        std_max = standard.get('max')

    WATER_STANDARDS[param_name] = {
        'name': param_display_names.get(param_name, param_name),
        'unit': param_units.get(param_name, ''),
        'type': std_type,
        'min': std_min,
        'max': std_max
    }


def find_std_for_param(param_key: str):
    nk = normalize_key(param_key)
    for k, v in WATER_STANDARDS.items():
        if normalize_key(k) == nk:
            return v
    return None


def standard_text(std: dict) -> str:
    if not std:
        return '-'
    t = std.get('type')
    if t == 'max':
        return f"≤ {std.get('max')}"
    if t == 'range':
        return f"{std.get('min')} – {std.get('max')}"
    # fallback
    if std.get('min') is not None and std.get('max') is not None:
        return f"{std.get('min')} – {std.get('max')}"
    if std.get('max') is not None:
        return f"≤ {std.get('max')}"
    return '-'


def classify_compliance(value, std: dict, tol=0.10):
    """
    Compliance ตามมาตรฐานจริง (ไม่ใช่ fuzzy)
    Near Limit = หลุดเกณฑ์เล็กน้อย (เช่น เกิน max ไม่เกิน 10%)
    """
    if value is None or not std:
        return 'N/A'

    t = std.get('type')

    # max only
    if t == 'max':
        mx = std.get('max')
        if mx is None:
            return 'N/A'
        if value <= mx:
            return 'Pass'
        if value <= mx * (1 + tol):
            return 'Near Limit'
        return 'Fail'

    # range
    if t == 'range':
        mn = std.get('min')
        mx = std.get('max')
        if mn is None or mx is None:
            return 'N/A'
        if mn <= value <= mx:
            return 'Pass'
        low_near = mn * (1 - tol)
        high_near = mx * (1 + tol)
        if low_near <= value <= high_near:
            return 'Near Limit'
        return 'Fail'

    return 'N/A'


def build_parameters(row):
    """ดึงค่าจาก DB row -> dict สำหรับ fuzzy (คีย์ต้องตรงกับ fuzzy_logic)"""
    def get_attr_any(obj, names, default=None):
        for n in names:
            if hasattr(obj, n):
                v = getattr(obj, n)
                if v is not None:
                    return v
        for n in names:
            if hasattr(obj, n):
                return getattr(obj, n)
        return default

    return {
        'pH': safe_float(get_attr_any(row, ['pH'])),
        'BOD': safe_float(get_attr_any(row, ['BOD'])),
        'COD': safe_float(get_attr_any(row, ['COD'])),
        'TSS': safe_float(get_attr_any(row, ['TSS'])),
        'TDS': safe_float(get_attr_any(row, ['TDS'])),
        'O&G': safe_float(get_attr_any(row, ['oil_grease', 'O_G', 'OG', 'OandG', 'O&G'])),
        'TKN': safe_float(get_attr_any(row, ['TKN'])),
        'Sulfide': safe_float(get_attr_any(row, ['sulfide', 'Sulfide'])),
        'TCB': safe_float(get_attr_any(row, ['TCB'])),
        'FCB': safe_float(get_attr_any(row, ['FCB'])),
        'Cl2': safe_float(get_attr_any(row, ['chlorine', 'Cl2', 'CL2'])),
    }


def can_fuzzy_eval(params: dict) -> bool:
    """กัน error/NoData: ต้องมีค่าครบทุกตัวตามที่ fuzzy_logic require"""
    for k in REQUIRED_FUZZY_COLS:
        if params.get(k) is None:
            return False
    return True


# =========================
# LOGIN
# =========================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/')
def index():
    return redirect(url_for('public_dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f'ยินดีต้อนรับ {user.full_name or user.username}!', 'success')
            return redirect(request.args.get('next') or url_for('dashboard'))
        else:
            flash('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('ออกจากระบบเรียบร้อย', 'success')
    return redirect(url_for('login'))


# =========================
# STATS
# =========================
def rule_based_status(param_name, value):
    """ใช้ WATER_STANDARDS เป็นฐานเดียว (คืน Pass/Near Limit/Fail/N/A)"""
    std = find_std_for_param(param_name)
    return classify_compliance(value, std, tol=0.10)


def calculate_detailed_statistics(location, pond, date_from, date_to):
    """คำนวณสถิติเชิงลึกสำหรับแต่ละพารามิเตอร์"""
    data_list = WaterQualityData.query.filter(
        WaterQualityData.sample_location == location,
        WaterQualityData.pond_name == pond,
        WaterQualityData.sample_date.between(date_from, date_to)
    ).order_by(WaterQualityData.sample_date.asc()).all()

    if not data_list:
        return None

    param_stats = {}

    parameters = {
        'pH': [d.pH for d in data_list if d.pH is not None],
        'BOD': [d.BOD for d in data_list if d.BOD is not None],
        'COD': [d.COD for d in data_list if d.COD is not None],
        'TSS': [d.TSS for d in data_list if d.TSS is not None],
        'TDS': [d.TDS for d in data_list if d.TDS is not None],
        'O&G': [d.oil_grease for d in data_list if d.oil_grease is not None],
        'TKN': [d.TKN for d in data_list if d.TKN is not None],
        'Sulfide': [d.sulfide for d in data_list if d.sulfide is not None],
        'TCB': [d.TCB for d in data_list if d.TCB is not None],
        'FCB': [d.FCB for d in data_list if d.FCB is not None],
        'Cl2': [d.chlorine for d in data_list if d.chlorine is not None]
    }

    for param_name, values in parameters.items():
        if not values:
            continue

        avg_val = sum(values) / len(values)
        min_val = min(values)
        max_val = max(values)
        latest_val = values[-1]
        standard = find_std_for_param(param_name) or {}

        pass_count = sum(1 for val in values if rule_based_status(param_name, val) == 'Pass')
        near_limit_count = sum(1 for val in values if rule_based_status(param_name, val) == 'Near Limit')
        fail_count = sum(1 for val in values if rule_based_status(param_name, val) == 'Fail')

        total_count = len(values)
        pass_rate = (pass_count / total_count * 100) if total_count > 0 else 0

        # trend
        trend = 'stable'
        if len(values) >= 4:
            mid_point = len(values) // 2
            first_half_avg = sum(values[:mid_point]) / mid_point
            second_half_avg = sum(values[mid_point:]) / (len(values) - mid_point)

            # สำหรับตัวที่ "ยิ่งน้อยยิ่งดี" เท่านั้น
            if param_name not in ['pH', 'Cl2']:
                if second_half_avg < first_half_avg * 0.9:
                    trend = 'improving'
                elif second_half_avg > first_half_avg * 1.1:
                    trend = 'worsening'

        current_status = rule_based_status(param_name, latest_val)

        param_stats[param_name] = {
            'name': standard.get('name', param_name),
            'unit': standard.get('unit', ''),
            'current': round(latest_val, 2),
            'average': round(avg_val, 2),
            'min': round(min_val, 2),
            'max': round(max_val, 2),
            'standard_min': standard.get('min'),
            'standard_max': standard.get('max'),
            'pass_rate': round(pass_rate, 1),
            'pass_count': pass_count,
            'near_limit_count': near_limit_count,
            'fail_count': fail_count,
            'total_count': total_count,
            'trend': trend,
            'status': current_status,
            'values': values
        }

    return param_stats


# =========================
# OVERVIEW (ALL PONDS)
# =========================
def calculate_all_ponds_overview(location, pond_list, date_from, date_to, calculation_mode='latest'):
    """
    คำนวณภาพรวมของทุกบ่อในสถานที่ โดยใช้ Fuzzy Logic
    calculation_mode: 'latest' | 'average' | 'weighted'
    """
    all_ponds_data = []

    for pond_name in pond_list:
        data_list = WaterQualityData.query.filter(
            WaterQualityData.sample_location == location,
            WaterQualityData.pond_name == pond_name,
            WaterQualityData.sample_date.between(date_from, date_to)
        ).order_by(WaterQualityData.sample_date.asc()).all()

        if not data_list:
            continue

        if calculation_mode == 'latest':
            latest_data = data_list[-1]
            parameters = build_parameters(latest_data)
            sample_date = latest_data.sample_date
            calculation_info = f"ข้อมูลล่าสุด ({latest_data.sample_date.strftime('%d/%m/%Y')})"

        elif calculation_mode == 'average':
            parameters = {}
            mapping = {
                'pH': 'pH', 'BOD': 'BOD', 'COD': 'COD', 'TSS': 'TSS', 'TDS': 'TDS',
                'O&G': 'oil_grease', 'TKN': 'TKN', 'Sulfide': 'sulfide', 'TCB': 'TCB',
                'FCB': 'FCB', 'Cl2': 'chlorine'
            }
            for k, attr in mapping.items():
                vals = [safe_float(getattr(d, attr)) for d in data_list if safe_float(getattr(d, attr)) is not None]
                parameters[k] = (sum(vals) / len(vals)) if vals else None
            sample_date = data_list[-1].sample_date
            calculation_info = f"ค่าเฉลี่ย {len(data_list)} วัน"

        else:  # weighted
            parameters = {}
            now = datetime.now()
            mapping = {
                'pH': 'pH', 'BOD': 'BOD', 'COD': 'COD', 'TSS': 'TSS', 'TDS': 'TDS',
                'O&G': 'oil_grease', 'TKN': 'TKN', 'Sulfide': 'sulfide', 'TCB': 'TCB',
                'FCB': 'FCB', 'Cl2': 'chlorine'
            }
            for k, attr in mapping.items():
                weighted_sum = 0.0
                total_weight = 0.0
                for d in data_list:
                    v = safe_float(getattr(d, attr))
                    if v is None:
                        continue
                    days_old = (now - d.sample_date).days
                    weight = 1.0 / (days_old + 1.0)
                    weighted_sum += v * weight
                    total_weight += weight
                parameters[k] = (weighted_sum / total_weight) if total_weight > 0 else None
            sample_date = data_list[-1].sample_date
            calculation_info = f"ค่าเฉลี่ยถ่วงน้ำหนัก {len(data_list)} วัน"

        # fuzzy evaluation (ต้องครบทุกตัว)
        if can_fuzzy_eval(parameters):
            fuzzy_eval = fuzzy_system.evaluate_overall(parameters)
            score = fuzzy_eval.get('overall_score')
            overall_status = score_to_overall_status(score)
        else:
            fuzzy_eval = {
                'overall_score': None,
                'overall_level': 'No Data',
                'overall_message': 'ข้อมูลไม่ครบสำหรับประเมิน Fuzzy (ต้องมีครบ 11 พารามิเตอร์)',
                'parameter_results': {},
                'fuzzy_membership': {}
            }
            score = None
            overall_status = 'No Data'

        # critical/warning params จากผล fuzzy per-parameter (ถ้ามี)
        critical_params, warning_params = [], []
        for param, result in (fuzzy_eval.get('parameter_results') or {}).items():
            if isinstance(result, dict):
                st = result.get('status')
                if st == 'Fail':
                    critical_params.append(param)
                elif st == 'Near Limit':
                    warning_params.append(param)

        pond_summary = {
            'pond_name': pond_name,
            'status': overall_status,
            'fuzzy_score': score,
            'fuzzy_message': fuzzy_eval.get('overall_message', ''),
            'sample_date': sample_date,
            'critical_count': 0,
            'warning_count': 0,
            'pass_count': 0,
            'total_parameters': 0,
            'critical_params': critical_params,
            'warning_params': warning_params,
            'parameter_results': fuzzy_eval.get('parameter_results', {}),
            'calculation_mode': calculation_mode,
            'calculation_info': calculation_info,
        }

        all_ponds_data.append(pond_summary)

    return all_ponds_data


def is_final_pond(name: str) -> bool:
    n = (name or "").lower()
    keywords = [
        "หลังบำบัด", "treated", "final", "effluent",
        "บ่อพักน้ำทิ้ง", "treated water tank"
    ]
    return any(k in n for k in keywords)


# =========================
# PUBLIC DASHBOARD
# =========================
@app.route('/public/dashboard')
def public_dashboard():
    latest_subq = db.session.query(
        WaterQualityData.sample_location.label('loc'),
        WaterQualityData.pond_name.label('pond'),
        func.max(WaterQualityData.sample_date).label('max_date')
    ).filter(
        WaterQualityData.sample_type == 'หลังบำบัด'
    ).group_by(
        WaterQualityData.sample_location, WaterQualityData.pond_name
    ).subquery()

    latest_rows = db.session.query(WaterQualityData).join(
        latest_subq,
        (WaterQualityData.sample_location == latest_subq.c.loc) &
        (WaterQualityData.pond_name == latest_subq.c.pond) &
        (WaterQualityData.sample_date == latest_subq.c.max_date)
    ).all()

    all_ponds = []
    for data in latest_rows:
        params = build_parameters(data)
        if can_fuzzy_eval(params):
            fuzzy_eval = fuzzy_system.evaluate_overall(params)
            score = fuzzy_eval.get('overall_score')
            status = score_to_overall_status(score)
        else:
            score = None
            status = 'No Data'

        all_ponds.append({
            'location': data.sample_location,
            'pond_name': data.pond_name,
            'sample_date': data.sample_date,
            'status': status,
            'fuzzy_score': score,
        })

    total_ponds = len(all_ponds)
    pass_ponds = sum(1 for p in all_ponds if p.get('status') == 'Pass')
    near_ponds = sum(1 for p in all_ponds if p.get('status') == 'Near Limit')
    fail_ponds = sum(1 for p in all_ponds if p.get('status') == 'Fail')

    valid_scores = [p['fuzzy_score'] for p in all_ponds if p.get('fuzzy_score') is not None]
    avg_score = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0

    overall_stats = {
        'total': total_ponds,
        'pass': pass_ponds,
        'near_limit': near_ponds,
        'fail': fail_ponds,
        'avg_score': avg_score,
        'pass_rate': round((pass_ponds / total_ponds * 100), 1) if total_ponds > 0 else 0
    }

    # trend 7 days
    seven_days_ago = datetime.now() - timedelta(days=7)
    trend_data = WaterQualityData.query.filter(
        WaterQualityData.sample_type == 'หลังบำบัด',
        WaterQualityData.sample_date >= seven_days_ago
    ).order_by(WaterQualityData.sample_date.asc()).all()

    trend_by_date = {}
    for data in trend_data:
        date_str = data.sample_date.strftime('%d/%m')
        trend_by_date.setdefault(date_str, [])
        params = build_parameters(data)
        if can_fuzzy_eval(params):
            score = fuzzy_system.evaluate_overall(params).get('overall_score')
            if score is not None:
                trend_by_date[date_str].append(score)

    trend_labels, trend_scores = [], []
    for date_str in sorted(trend_by_date.keys()):
        scores = [s for s in trend_by_date[date_str] if s is not None]
        if scores:
            trend_labels.append(date_str)
            trend_scores.append(round(sum(scores) / len(scores), 1))

    return render_template(
        'public_dashboard.html',
        all_ponds=all_ponds,
        overall_stats=overall_stats,
        trend_labels=trend_labels,
        trend_scores=trend_scores,
        water_standards=to_object(WATER_STANDARDS),
        last_update=datetime.now()
    )


# =========================
# MAIN DASHBOARD
# =========================
def _day_range(dt: datetime):
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return day_start, day_end


def pick_latest_by_keywords_in_day(selected_location, sample_type, keywords, day_start, day_end):
    q = WaterQualityData.query.filter(
        WaterQualityData.sample_location == selected_location,
        WaterQualityData.sample_type == sample_type,
        WaterQualityData.sample_date.between(day_start, day_end)
    )
    cond = None
    for kw in keywords:
        c = WaterQualityData.pond_name.ilike(f"%{kw}%")
        cond = c if cond is None else (cond | c)
    if cond is not None:
        q = q.filter(cond)
    return q.order_by(WaterQualityData.sample_date.desc()).first()


def percent_reduction(before, after):
    if before is None or after is None:
        return None
    try:
        before = float(before)
        after = float(after)
        if before <= 0:
            return None
        return round((before - after) / before * 100.0, 1)
    except Exception:
        return None


@app.route('/dashboard')
@login_required
def dashboard():
    # ===== LOCATION / POND =====
    locations = db.session.query(WaterQualityData.sample_location).distinct().filter(
        WaterQualityData.sample_location.isnot(None),
        WaterQualityData.sample_location != ''
    ).all()
    location_list = [loc[0] for loc in locations if loc[0]]

    latest_loc = db.session.query(WaterQualityData.sample_location).filter(
        WaterQualityData.sample_type == 'หลังบำบัด',
        WaterQualityData.sample_location.isnot(None),
        WaterQualityData.sample_location != ''
    ).order_by(WaterQualityData.sample_date.desc()).first()

    default_location = latest_loc[0] if latest_loc else (location_list[0] if location_list else None)
    selected_location = request.args.get('location', default_location)

    ponds = db.session.query(WaterQualityData.pond_name).distinct().filter(
        WaterQualityData.sample_location == selected_location
    ).all()
    pond_list = [p[0] for p in ponds if p[0]]

    selected_pond = request.args.get('pond', 'ทั้งหมด') or 'ทั้งหมด'

    # ===== DATE HANDLING =====
    mode = (request.args.get('mode') or 'latest').lower()
    month_arg = request.args.get('month')
    date_from_arg = request.args.get('date_from')
    date_to_arg = request.args.get('date_to')

    selected_month = month_arg or datetime.now().strftime('%Y-%m')

    def month_start_end(yyyy_mm: str):
        y, m = map(int, yyyy_mm.split('-'))
        start = datetime(y, m, 1, 0, 0, 0)
        if m == 12:
            next_month = datetime(y + 1, 1, 1, 0, 0, 0)
        else:
            next_month = datetime(y, m + 1, 1, 0, 0, 0)
        end = next_month - timedelta(seconds=1)
        return start, end

    date_mode = 'latest'
    date_from_str = ''
    date_to_str = ''
    display_date_text = ''

    if mode == 'range':
        if date_from_arg and date_to_arg:
            date_from = datetime.strptime(date_from_arg, '%Y-%m-%d')
            date_to = datetime.strptime(date_to_arg, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            date_mode = 'range'
            date_from_str, date_to_str = date_from_arg, date_to_arg
            display_date_text = f"แสดงผลจากวันที่ {date_from_arg} ถึง {date_to_arg}"
        else:
            mode = 'latest'

    if mode == 'month':
        try:
            date_from, date_to = month_start_end(selected_month)
            date_mode = 'month'
            date_from_str = date_from.strftime('%Y-%m-%d')
            date_to_str = date_to.strftime('%Y-%m-%d')
            display_date_text = f"แสดงผลแบบเดือน: {selected_month} (ดึงข้อมูลล่าสุดในเดือน)"
        except Exception:
            mode = 'latest'

    if mode == 'latest':
        latest_record = WaterQualityData.query.filter(
            WaterQualityData.sample_location == selected_location,
            WaterQualityData.sample_type == 'หลังบำบัด'
        ).order_by(WaterQualityData.sample_date.desc()).first()

        if latest_record:
            date_from = latest_record.sample_date.replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = latest_record.sample_date.replace(hour=23, minute=59, second=59, microsecond=0)
            date_from_str = latest_record.sample_date.strftime('%Y-%m-%d')
            date_to_str = latest_record.sample_date.strftime('%Y-%m-%d')
            date_mode = 'latest'
            display_date_text = f"แสดงผลจากข้อมูลล่าสุด ณ วันที่ {latest_record.sample_date.strftime('%d/%m/%Y %H:%M')}"
        else:
            date_from = datetime.now()
            date_to = datetime.now()
            display_date_text = "ไม่พบข้อมูลล่าสุด"

    # =========================
    # OVERVIEW MODE
    # =========================
    if selected_pond == 'ทั้งหมด':
        calculation_mode = request.args.get('calc_mode', 'latest')

        all_ponds_overview = calculate_all_ponds_overview(
            selected_location, pond_list, date_from, date_to, calculation_mode
        )

        # ✅ ปักหมุดบ่อหลังบำบัดบนสุด
        all_ponds_overview.sort(key=lambda p: (
            0 if is_final_pond(p.get('pond_name')) else 1,
            -(p.get('fuzzy_score') if p.get('fuzzy_score') is not None else -1),
            -(p.get('sample_date').timestamp() if p.get('sample_date') else 0)
        ))

        overview_stats = {
            'total': len(all_ponds_overview),
            'pass': sum(1 for p in all_ponds_overview if p.get('status') == 'Pass'),
            'near_limit': sum(1 for p in all_ponds_overview if p.get('status') == 'Near Limit'),
            'fail': sum(1 for p in all_ponds_overview if p.get('status') == 'Fail')
        }

        # =========================
        # ประสิทธิภาพการบำบัด (วันเดียวกัน)
        # =========================
        stage_compare = []
        reduction = {}
        match_date_text = None

        final_item = next((p for p in all_ponds_overview if is_final_pond(p.get('pond_name'))), None)
        matched_day_dt = final_item.get('sample_date') if final_item else None

        if matched_day_dt:
            day_start, day_end = _day_range(matched_day_dt)
            match_date_text = matched_day_dt.strftime('%d/%m/%Y')

            eq_row = pick_latest_by_keywords_in_day(
                selected_location, 'ก่อนบำบัด',
                ['บ่อรวบรวมนํ้าเสีย', 'บ่อรวบรวมน้ำเสีย', 'Equalization', 'Collection', 'รวบรวม'],
                day_start, day_end
            )
            aer_row = pick_latest_by_keywords_in_day(
                selected_location, 'กำลังบำบัด',
                ['บ่อเติมอากาศ', 'Aeration', 'เติมอากาศ'],
                day_start, day_end
            )
            sed_row = pick_latest_by_keywords_in_day(
                selected_location, 'กำลังบำบัด',
                ['บ่อตกตะกอน', 'Sedimentation', 'ตกตะกอน'],
                day_start, day_end
            )
            final_row = WaterQualityData.query.filter(
                WaterQualityData.sample_location == selected_location,
                WaterQualityData.sample_type == 'หลังบำบัด',
                WaterQualityData.sample_date.between(day_start, day_end)
            ).filter(
                WaterQualityData.pond_name.ilike(f"%{final_item.get('pond_name')}%")
            ).order_by(WaterQualityData.sample_date.desc()).first()

            def stage_row(title, row):
                if not row:
                    return None
                p = build_parameters(row)
                fr = fuzzy_system.evaluate_overall(p) if can_fuzzy_eval(p) else {}
                score = fr.get('overall_score')
                return {
                    'stage': title,
                    'pond_name': getattr(row, 'pond_name', '-'),
                    'sample_type': getattr(row, 'sample_type', '-'),
                    'BOD': p.get('BOD'),
                    'COD': p.get('COD'),
                    'TSS': p.get('TSS'),
                    'FCB': p.get('FCB'),
                    'TCB': p.get('TCB'),
                    'score': score,
                    'status': score_to_overall_status(score),
                }

            for title, row in [
                ('ก่อนบำบัด (บ่อรวบรวม)', eq_row),
                ('กำลังบำบัด (เติมอากาศ)', aer_row),
                ('กำลังบำบัด (ตกตะกอน)', sed_row),
                ('หลังบำบัด (บ่อพักน้ำทิ้ง)', final_row),
            ]:
                sr = stage_row(title, row)
                if sr:
                    stage_compare.append(sr)

            if eq_row and final_row:
                b = build_parameters(eq_row)
                a = build_parameters(final_row)
                reduction = {
                    'BOD': percent_reduction(b.get('BOD'), a.get('BOD')),
                    'COD': percent_reduction(b.get('COD'), a.get('COD')),
                    'TSS': percent_reduction(b.get('TSS'), a.get('TSS')),
                    'FCB': percent_reduction(b.get('FCB'), a.get('FCB')),
                    'TCB': percent_reduction(b.get('TCB'), a.get('TCB')),
                }

        return render_template(
            'enhanced_dashboard.html',
            location_list=location_list,
            pond_list=pond_list,
            selected_location=selected_location,
            selected_pond=selected_pond,
            all_ponds_overview=all_ponds_overview,
            overview_stats=overview_stats,
            calculation_mode=calculation_mode,
            display_date_text=display_date_text,
            date_mode=date_mode,
            date_from=date_from_str,
            date_to=date_to_str,
            selected_month=selected_month,
            stage_compare=stage_compare,
            reduction=reduction,
            match_date_text=match_date_text,
            water_standards=to_object(WATER_STANDARDS)
        )

    # =========================
    # DETAIL MODE (SINGLE POND)
    # =========================
    after_q = WaterQualityData.query.filter(
        WaterQualityData.sample_location == selected_location,
        WaterQualityData.pond_name == selected_pond,
        WaterQualityData.sample_date.between(date_from, date_to)
    ).order_by(WaterQualityData.sample_date.desc())

    after_count = after_q.count()
    after_data = after_q.first()

    # fallback latest if range empty
    if after_data is None:
        latest_any = WaterQualityData.query.filter(
            WaterQualityData.sample_location == selected_location,
            WaterQualityData.pond_name == selected_pond
        ).order_by(WaterQualityData.sample_date.desc()).first()

        if latest_any:
            date_from = latest_any.sample_date.replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = latest_any.sample_date.replace(hour=23, minute=59, second=59, microsecond=0)
            date_from_str = date_from.strftime('%Y-%m-%d')
            date_to_str = date_to.strftime('%Y-%m-%d')
            date_mode = 'latest'
            display_date_text = (
                f"⚠️ ช่วงวันที่ที่เลือกไม่มีข้อมูลของบ่อนี้ "
                f"จึงแสดงข้อมูลล่าสุดแทน ณ {latest_any.sample_date.strftime('%d/%m/%Y %H:%M')}"
            )
            after_data = latest_any
            after_count = 1

    # =========================
    # STAGE COMPARISON + REDUCTION
    # =========================
    stage_latest = {'equalization': None, 'aeration': None, 'sedimentation': None, 'treated': after_data}
    stage_compare = []
    reduction = {}

    def pick_latest_by_keyword(sample_type, keywords, day_start, day_end):
        q = WaterQualityData.query.filter(
            WaterQualityData.sample_location == selected_location,
            WaterQualityData.sample_type == sample_type,
            WaterQualityData.sample_date.between(day_start, day_end)
        )
        cond = None
        for kw in keywords:
            c = WaterQualityData.pond_name.ilike(f"%{kw}%")
            cond = c if cond is None else (cond | c)
        if cond is not None:
            q = q.filter(cond)
        return q.order_by(WaterQualityData.sample_date.desc()).first()

    if after_data is not None and after_data.sample_date is not None:
        day_start, day_end = _day_range(after_data.sample_date)

        stage_latest['equalization'] = pick_latest_by_keyword(
            'ก่อนบำบัด',
            ['บ่อรวบรวมนํ้าเสีย', 'บ่อรวบรวมน้ำเสีย', 'Equalization', 'Collection', 'รวบรวม'],
            day_start, day_end
        )
        stage_latest['aeration'] = pick_latest_by_keyword(
            'กำลังบำบัด',
            ['บ่อเติมอากาศ', 'Aeration', 'เติมอากาศ'],
            day_start, day_end
        )
        stage_latest['sedimentation'] = pick_latest_by_keyword(
            'กำลังบำบัด',
            ['บ่อตกตะกอน', 'Sedimentation', 'ตกตะกอน'],
            day_start, day_end
        )

    pond_data = {
        'before': {'latest': stage_latest['equalization']},
        'inprocess': {'latest': stage_latest['aeration'] or stage_latest['sedimentation']},
        'after': {'latest': stage_latest['treated']},
        'stages': stage_latest
    }

    def stage_row(stage_name, sample_type, row):
        if row is None:
            return None
        p = build_parameters(row)
        if can_fuzzy_eval(p):
            fr = fuzzy_system.evaluate_overall(p)
            score = fr.get('overall_score')
        else:
            score = None
        return {
            'stage': stage_name,
            'sample_type': sample_type,
            'pond_name': getattr(row, 'pond_name', '-') if row else '-',
            'BOD': p.get('BOD'),
            'COD': p.get('COD'),
            'TSS': p.get('TSS'),
            'FCB': p.get('FCB'),
            'TCB': p.get('TCB'),
            'score': score,
            'status': score_to_overall_status(score),
        }

    for (nm, tp, key) in [
        ('ก่อนบำบัด (บ่อรวบรวม)', 'ก่อนบำบัด', 'equalization'),
        ('กำลังบำบัด (เติมอากาศ)', 'กำลังบำบัด', 'aeration'),
        ('กำลังบำบัด (ตกตะกอน)', 'กำลังบำบัด', 'sedimentation'),
        ('หลังบำบัด (บ่อพักน้ำทิ้ง)', 'หลังบำบัด', 'treated'),
    ]:
        r = stage_row(nm, tp, stage_latest.get(key))
        if r:
            stage_compare.append(r)

    if stage_latest.get('equalization') and stage_latest.get('treated'):
        b = build_parameters(stage_latest['equalization'])
        a = build_parameters(stage_latest['treated'])
        reduction = {
            'BOD': percent_reduction(b.get('BOD'), a.get('BOD')),
            'COD': percent_reduction(b.get('COD'), a.get('COD')),
            'TSS': percent_reduction(b.get('TSS'), a.get('TSS')),
            'FCB': percent_reduction(b.get('FCB'), a.get('FCB')),
            'TCB': percent_reduction(b.get('TCB'), a.get('TCB')),
        }

    # =========================
    # FUZZY + COMPLIANCE TABLE
    # =========================
    score_value = None
    overall_status = 'No Data'
    overall_message = ''
    fuzzy_membership = {}
    parameter_results = {}
    param_rows = []

    compliance_counts = {'pass': 0, 'near': 0, 'fail': 0, 'na': 0}
    reasons_fail = []
    reasons_near = []

    if after_data is not None:
        params = build_parameters(after_data)

        if can_fuzzy_eval(params):
            fuzzy_result = fuzzy_system.evaluate_overall(params)
        else:
            fuzzy_result = {
                'overall_score': None,
                'overall_level': 'No Data',
                'band_by_score': 'No Data',
                'overall_message': 'ข้อมูลไม่ครบสำหรับประเมิน Fuzzy (ต้องมีครบ 11 พารามิเตอร์)',
                'parameter_results': {},
                'fuzzy_membership': {}
            }

        score_value = fuzzy_result.get('overall_score')
        overall_status = score_to_overall_status(score_value)
        overall_message = fuzzy_result.get('overall_message') or ''
        fuzzy_membership = fuzzy_result.get('fuzzy_membership') or {}
        parameter_results = fuzzy_result.get('parameter_results') or {}

        order_keys = ['pH', 'BOD', 'COD', 'TSS', 'TDS', 'O&G', 'TKN', 'Sulfide', 'TCB', 'FCB', 'Cl2']
        for k in order_keys:
            v = params.get(k)
            std = find_std_for_param(k)
            comp = classify_compliance(v, std, tol=0.10)

            if comp == 'Pass':
                compliance_counts['pass'] += 1
            elif comp == 'Near Limit':
                compliance_counts['near'] += 1
                reasons_near.append(k)
            elif comp == 'Fail':
                compliance_counts['fail'] += 1
                reasons_fail.append(k)
            else:
                compliance_counts['na'] += 1

            pr = parameter_results.get(k, {}) if isinstance(parameter_results, dict) else {}
            # ✅ ทำให้ template/ตารางไม่พังแม้ไม่มี risk_percent (กันไว้ชั้น backend ด้วย)
            risk_percent = pr.get('risk_percent', 0) if isinstance(pr, dict) else 0

            param_rows.append({
                'label': k,
                'value': v,
                'standard': standard_text(std if isinstance(std, dict) else None),
                'status': comp,
                'fuzzy_term': pr.get('dominant_term'),
                'membership_degree': pr.get('dominant_mu'),
                'risk_percent': risk_percent,
                'risk_level': pr.get('status'),
            })

    total_params = len(param_rows)
    compliance_rate = round((compliance_counts['pass'] / total_params) * 100, 1) if total_params > 0 else 0.0

    # =========================
    # param_stats
    # =========================
    param_stats = calculate_detailed_statistics(selected_location, selected_pond, date_from, date_to)

    return render_template(
        'enhanced_dashboard.html',
        location_list=location_list,
        pond_list=pond_list,
        selected_location=selected_location,
        selected_pond=selected_pond,
        display_date_text=display_date_text,
        date_mode=date_mode,
        date_from=date_from_str,
        date_to=date_to_str,
        selected_month=selected_month,
        mode=mode,
        after_data=after_data,
        after_count=after_count,
        pond_data=pond_data,
        score_value=score_value,
        overall_status=overall_status,
        overall_message=overall_message,
        fuzzy_membership=fuzzy_membership,
        parameter_results=parameter_results,
        param_rows=param_rows,
        compliance_counts=compliance_counts,
        compliance_rate=compliance_rate,
        reasons_fail=reasons_fail,
        reasons_near=reasons_near,
        reduction=reduction,
        stage_compare=stage_compare,
        param_stats=param_stats,
        water_standards=to_object(WATER_STANDARDS)
    )


# =========================
# ADD DATA
# =========================
@app.route('/data/add', methods=['GET', 'POST'])
@login_required
def add_data():
    if request.method == 'POST':
        try:
            sample_location = request.form.get('sample_location', '').strip()
            if not sample_location:
                flash('กรุณาระบุสถานที่เก็บตัวอย่าง', 'error')
                return redirect(url_for('add_data'))

            sample_date_raw = request.form.get('sample_date')
            if not sample_date_raw:
                flash('กรุณาระบุวันเวลาเก็บตัวอย่าง', 'error')
                return redirect(url_for('add_data'))

            sample_date = datetime.strptime(sample_date_raw, '%Y-%m-%dT%H:%M')

            pond_name = request.form.get('pond_name', '').strip()
            if not pond_name:
                flash('กรุณาระบุชื่อบ่อ/ระบบบำบัด', 'error')
                return redirect(url_for('add_data'))

            sample_type = request.form.get('sample_type', 'หลังบำบัด')

            water_data = WaterQualityData(
                user_id=current_user.id,
                sample_date=sample_date,
                sample_location=sample_location,
                pond_name=pond_name,
                sample_type=sample_type,
                pH=get_float(request.form, 'pH'),
                BOD=get_float(request.form, 'BOD'),
                COD=get_float(request.form, 'COD'),
                TSS=get_float(request.form, 'TSS'),
                TDS=get_float(request.form, 'TDS'),
                oil_grease=get_float(request.form, 'oil_grease'),
                TKN=get_float(request.form, 'TKN'),
                sulfide=get_float(request.form, 'sulfide'),
                TCB=get_float(request.form, 'TCB'),
                FCB=get_float(request.form, 'FCB'),
                chlorine=get_float(request.form, 'chlorine'),
                ammonium=get_float(request.form, 'ammonium'),
                dissolved_oxygen=get_float(request.form, 'dissolved_oxygen'),
            )

            db.session.add(water_data)
            db.session.flush()

            if sample_type == 'หลังบำบัด':
                params = build_parameters(water_data)

                if can_fuzzy_eval(params):
                    evaluation = fuzzy_system.evaluate_overall(params)
                    score = evaluation.get('overall_score')
                    pr = evaluation.get('parameter_results', {}) or {}

                    result = EvaluationResult(
                        water_data_id=water_data.id,
                        overall_status=score_to_overall_status(score),
                        overall_score=score,
                        overall_message=evaluation.get('overall_message', ''),
                        pass_count=0,
                        near_limit_count=0,
                        fail_count=0,
                        total_parameters=0,
                        pH_result=pr.get('pH'),
                        BOD_result=pr.get('BOD'),
                        COD_result=pr.get('COD'),
                        TSS_result=pr.get('TSS'),
                        TDS_result=pr.get('TDS'),
                        oil_grease_result=pr.get('O&G'),
                        TKN_result=pr.get('TKN'),
                        sulfide_result=pr.get('Sulfide'),
                        TCB_result=pr.get('TCB'),
                        FCB_result=pr.get('FCB'),
                        chlorine_result=pr.get('Cl2'),
                    )
                    db.session.add(result)
                    db.session.commit()
                    flash('บันทึกข้อมูลและประเมินเรียบร้อย!', 'success')
                    return redirect(url_for('view_result', result_id=result.id))
                else:
                    db.session.commit()
                    flash('บันทึกข้อมูลแล้ว แต่ข้อมูลไม่ครบสำหรับประเมิน Fuzzy', 'warning')
                    return redirect(url_for('dashboard'))

            db.session.commit()
            flash('บันทึกข้อมูลเรียบร้อย!', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            db.session.rollback()
            flash(f'เกิดข้อผิดพลาด: {str(e)}', 'error')
            return redirect(url_for('add_data'))

    return render_template('add_data.html', water_standards=to_object(WATER_STANDARDS))


# =========================
# UPLOAD DATA
# =========================
@app.route('/data/upload', methods=['GET', 'POST'])
@login_required
def upload_data():
    if request.method != 'POST':
        return render_template('upload_data.html', water_standards=to_object(WATER_STANDARDS))

    if 'file' not in request.files:
        flash('ไม่พบไฟล์', 'error')
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        flash('ไม่ได้เลือกไฟล์', 'error')
        return redirect(request.url)

    if not (file and allowed_file(file.filename)):
        flash('ไฟล์ต้องเป็น .xlsx หรือ .xls เท่านั้น', 'error')
        return redirect(request.url)

    try:
        df = pd.read_excel(file)

        required_columns = [
            'sample_date', 'sample_location', 'pond_name', 'sample_type',
            'pH', 'BOD', 'COD', 'TSS', 'TDS', 'O&G',
            'TKN', 'sulfide', 'TCB', 'FCB', 'Cl2'
        ]

        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            flash(f'ไฟล์ Excel ขาดคอลัมน์: {", ".join(missing_columns)}', 'error')
            return redirect(request.url)

        success_count = 0
        error_count = 0
        valid_dates = []
        last_location_uploaded = None

        for _, row in df.iterrows():
            try:
                with db.session.begin_nested():
                    loc = row.get('sample_location')
                    pond = row.get('pond_name')

                    if is_missing(loc) or is_missing(pond):
                        error_count += 1
                        continue

                    sample_location = str(loc).strip()
                    pond_name = str(pond).strip()

                    st = row.get('sample_type', 'หลังบำบัด')
                    sample_type = 'หลังบำบัด' if is_missing(st) else str(st).strip()

                    try:
                        sample_date = pd.to_datetime(row.get('sample_date'))
                        if pd.isna(sample_date):
                            raise ValueError("sample_date is NaT")
                    except Exception:
                        error_count += 1
                        continue

                    pH = safe_float(row.get('pH'))
                    BOD = safe_float(row.get('BOD'))
                    COD = safe_float(row.get('COD'))
                    TSS = safe_float(row.get('TSS'))
                    TDS = safe_float(row.get('TDS'))
                    oil_grease = safe_float(row.get('O&G'))
                    TKN = safe_float(row.get('TKN'))
                    sulfide = safe_float(row.get('sulfide'))
                    TCB = safe_float(row.get('TCB'))
                    FCB = safe_float(row.get('FCB'))
                    chlorine = safe_float(row.get('Cl2'))

                    ammonium = safe_float(row.get('NH4')) if 'NH4' in df.columns else None
                    dissolved_oxygen = safe_float(row.get('DO')) if 'DO' in df.columns else None

                    existing = WaterQualityData.query.filter_by(
                        sample_date=sample_date,
                        sample_location=sample_location,
                        pond_name=pond_name,
                        sample_type=sample_type
                    ).first()

                    if existing:
                        water_data = existing
                    else:
                        water_data = WaterQualityData(
                            user_id=current_user.id,
                            sample_date=sample_date,
                            sample_location=sample_location,
                            pond_name=pond_name,
                            sample_type=sample_type,
                        )
                        db.session.add(water_data)

                    water_data.user_id = current_user.id
                    water_data.pH = pH
                    water_data.BOD = BOD
                    water_data.COD = COD
                    water_data.TSS = TSS
                    water_data.TDS = TDS
                    water_data.oil_grease = oil_grease
                    water_data.TKN = TKN
                    water_data.sulfide = sulfide
                    water_data.TCB = TCB
                    water_data.FCB = FCB
                    water_data.chlorine = chlorine
                    water_data.ammonium = ammonium
                    water_data.dissolved_oxygen = dissolved_oxygen

                    db.session.flush()

                    # Evaluate เฉพาะหลังบำบัด
                    if water_data.sample_type == 'หลังบำบัด':
                        params = build_parameters(water_data)

                        if can_fuzzy_eval(params):
                            evaluation = fuzzy_system.evaluate_overall(params)
                            pr = evaluation.get('parameter_results', {}) or {}
                            overall_score = evaluation.get('overall_score')

                            if overall_score is not None:
                                result = EvaluationResult.query.filter_by(water_data_id=water_data.id).first()
                                if not result:
                                    result = EvaluationResult(water_data_id=water_data.id)
                                    db.session.add(result)

                                result.overall_status = score_to_overall_status(overall_score)
                                result.overall_score = float(overall_score)
                                result.overall_message = evaluation.get('overall_message', '')
                                result.pass_count = 0
                                result.near_limit_count = 0
                                result.fail_count = 0
                                result.total_parameters = 0

                                result.pH_result = pr.get('pH')
                                result.BOD_result = pr.get('BOD')
                                result.COD_result = pr.get('COD')
                                result.TSS_result = pr.get('TSS')
                                result.TDS_result = pr.get('TDS')
                                result.oil_grease_result = pr.get('O&G')
                                result.TKN_result = pr.get('TKN')
                                result.sulfide_result = pr.get('Sulfide')
                                result.TCB_result = pr.get('TCB')
                                result.FCB_result = pr.get('FCB')
                                result.chlorine_result = pr.get('Cl2')

                    success_count += 1
                    valid_dates.append(sample_date)
                    last_location_uploaded = sample_location

            except IntegrityError:
                error_count += 1
                continue
            except Exception:
                error_count += 1
                continue

        db.session.commit()

        latest_date_str = max(valid_dates).strftime('%Y-%m-%d') if valid_dates else None
        flash(
            f'อัปโหลดสำเร็จ {success_count} รายการ' +
            (f', มีข้อผิดพลาด {error_count} รายการ' if error_count > 0 else ''),
            'success'
        )

        if latest_date_str and last_location_uploaded:
            return redirect(url_for(
                'dashboard',
                location=last_location_uploaded,
                date_from=latest_date_str,
                date_to=latest_date_str
            ))

        return redirect(url_for('dashboard'))

    except Exception as e:
        db.session.rollback()
        flash(f'เกิดข้อผิดพลาดในการอ่านไฟล์: {str(e)}', 'error')
        return redirect(request.url)


@app.route('/data/edit/<int:water_data_id>', methods=['GET', 'POST'])
@login_required
def edit_data(water_data_id):
    water_data = WaterQualityData.query.get_or_404(water_data_id)

    if request.method == 'POST':
        try:
            sample_location = (request.form.get('sample_location') or '').strip()
            pond_name = (request.form.get('pond_name') or '').strip()
            sample_type = (request.form.get('sample_type') or '').strip()

            sample_date_raw = request.form.get('sample_date')
            if not sample_date_raw:
                flash('กรุณาระบุวันเวลาเก็บตัวอย่าง', 'error')
                return redirect(url_for('edit_data', water_data_id=water_data_id))
            sample_date = datetime.strptime(sample_date_raw, '%Y-%m-%dT%H:%M')

            if not sample_location:
                flash('กรุณาระบุสถานที่เก็บตัวอย่าง', 'error')
                return redirect(url_for('edit_data', water_data_id=water_data_id))
            if not pond_name:
                flash('กรุณาระบุชื่อบ่อ/ระบบบำบัด', 'error')
                return redirect(url_for('edit_data', water_data_id=water_data_id))
            if not sample_type:
                sample_type = 'หลังบำบัด'

            water_data.sample_location = sample_location
            water_data.pond_name = pond_name
            water_data.sample_type = sample_type
            water_data.sample_date = sample_date

            water_data.pH = get_float(request.form, 'pH')
            water_data.BOD = get_float(request.form, 'BOD')
            water_data.COD = get_float(request.form, 'COD')
            water_data.TSS = get_float(request.form, 'TSS')
            water_data.TDS = get_float(request.form, 'TDS')
            water_data.oil_grease = get_float(request.form, 'oil_grease')
            water_data.TKN = get_float(request.form, 'TKN')
            water_data.sulfide = get_float(request.form, 'sulfide')
            water_data.TCB = get_float(request.form, 'TCB')
            water_data.FCB = get_float(request.form, 'FCB')
            water_data.chlorine = get_float(request.form, 'chlorine')

            water_data.ammonium = get_float(request.form, 'ammonium')
            water_data.dissolved_oxygen = get_float(request.form, 'dissolved_oxygen')

            db.session.flush()

            if water_data.sample_type == 'หลังบำบัด':
                params = build_parameters(water_data)
                evaluation = fuzzy_system.evaluate_overall(params) if can_fuzzy_eval(params) else {
                    'overall_score': None,
                    'overall_message': 'ข้อมูลไม่ครบสำหรับประเมิน Fuzzy (ต้องมีครบ 11 พารามิเตอร์)',
                    'parameter_results': {}
                }
                score = evaluation.get('overall_score')

                result = EvaluationResult.query.filter_by(water_data_id=water_data.id).first()
                if not result:
                    result = EvaluationResult(water_data_id=water_data.id)
                    db.session.add(result)

                result.overall_status = score_to_overall_status(score)
                result.overall_score = score
                result.overall_message = evaluation.get('overall_message', '')

                pr = evaluation.get('parameter_results', {}) or {}
                result.pH_result = pr.get('pH')
                result.BOD_result = pr.get('BOD')
                result.COD_result = pr.get('COD')
                result.TSS_result = pr.get('TSS')
                result.TDS_result = pr.get('TDS')
                result.oil_grease_result = pr.get('O&G')
                result.TKN_result = pr.get('TKN')
                result.sulfide_result = pr.get('Sulfide')
                result.TCB_result = pr.get('TCB')
                result.FCB_result = pr.get('FCB')
                result.chlorine_result = pr.get('Cl2')

            db.session.commit()
            flash('บันทึกการแก้ไขเรียบร้อย!', 'success')
            return redirect(url_for('dashboard', location=water_data.sample_location, pond=water_data.pond_name))

        except Exception as e:
            db.session.rollback()
            flash(f'เกิดข้อผิดพลาด: {str(e)}', 'error')
            return redirect(url_for('edit_data', water_data_id=water_data_id))

    return render_template('result.html', water_data=water_data, water_standards=to_object(WATER_STANDARDS))


@app.route('/data/delete/<int:water_data_id>', methods=['POST'])
@login_required
def delete_data(water_data_id):
    data = WaterQualityData.query.get_or_404(water_data_id)

    if getattr(data, 'user_id', None) != current_user.id:
        flash('คุณไม่มีสิทธิ์ลบข้อมูลนี้', 'error')
        return redirect(url_for('history'))

    try:
        result = EvaluationResult.query.filter_by(water_data_id=data.id).first()
        if result:
            db.session.delete(result)

        db.session.delete(data)
        db.session.commit()
        flash('ลบข้อมูลเรียบร้อยแล้ว', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'ลบไม่สำเร็จ: {str(e)}', 'error')

    page = request.args.get('page', 1, type=int)
    return redirect(url_for('history', page=page))


# =========================
# RESULT VIEW
# =========================
@app.route('/result/<int:result_id>')
@login_required
def view_result(result_id):
    result = EvaluationResult.query.get_or_404(result_id)
    water_data = result.water_data
    parameter_results = []

    # ✅ compute fresh risk_percent for backward compatibility (old DB results)
    live_pr = {}
    try:
        params_live = build_parameters(water_data)
        if can_fuzzy_eval(params_live):
            live_eval = fuzzy_system.evaluate_overall(params_live)
            live_pr = live_eval.get('parameter_results', {}) or {}
    except Exception:
        live_pr = {}

    params = [
        ('pH', result.pH_result),
        ('BOD', result.BOD_result),
        ('COD', result.COD_result),
        ('TSS', result.TSS_result),
        ('TDS', result.TDS_result),
        ('O&G', result.oil_grease_result),
        ('TKN', result.TKN_result),
        ('Sulfide', result.sulfide_result),
        ('TCB', result.TCB_result),
        ('FCB', result.FCB_result),
        ('Cl2', result.chlorine_result),
    ]

    for param_name, param_result in params:
        if param_result:
            standard_info = find_std_for_param(param_name) or {}
            std_text = standard_text(standard_info)

            enriched = dict(param_result) if isinstance(param_result, dict) else {}
            enriched['unit'] = standard_info.get('unit', '')
            enriched['standard'] = std_text

            # ✅ ensure risk_percent exists (use saved value first, else use live computed)
            if 'risk_percent' not in enriched:
                enriched['risk_percent'] = (live_pr.get(param_name, {}) or {}).get('risk_percent', 0)
            if 'status' not in enriched:
                enriched['status'] = (live_pr.get(param_name, {}) or {}).get('status', 'N/A')

            parameter_results.append({
                'name': standard_info.get('name', param_name),
                'data': enriched
            })

    return render_template(
        'result.html',
        result=result,
        water_data=water_data,
        parameter_results=parameter_results,
        water_standards=to_object(WATER_STANDARDS)
    )


# =========================
# HISTORY
# =========================
@app.route('/history')
@login_required
def history():
    page = request.args.get('page', 1, type=int)
    pagination = WaterQualityData.query.order_by(WaterQualityData.sample_date.desc()).paginate(
        page=page, per_page=app.config['ITEMS_PER_PAGE'], error_out=False
    )
    return render_template('history.html', pagination=pagination, water_standards=to_object(WATER_STANDARDS))


# =========================
# ERROR HANDLERS
# =========================
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html', water_standards=to_object(WATER_STANDARDS)), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html', water_standards=to_object(WATER_STANDARDS)), 500


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
