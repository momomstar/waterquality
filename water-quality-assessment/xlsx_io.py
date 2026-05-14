# -*- coding: utf-8 -*-
"""
xlsx_io.py
----------
ฟังก์ชันช่วยงานไฟล์ Excel สำหรับระบบตรวจคุณภาพน้ำ
 1) normalize_hospital_xlsx(file)  →  DataFrame รูปแบบมาตรฐาน (flat)
    รองรับทั้ง
      • ไฟล์รูปแบบ flat เดิม (sample_data.xlsx)
      • ไฟล์รูปแบบ "ต่อโรงพยาบาล" (หลายชีต, header 2 แถว, มีแถว 'มาตรฐาน')
    แปลงค่าพิเศษ:
      • 'ไม่พบ'         → 0     (ค่าที่ต่ำกว่าขีดตรวจวัด ≈ ผ่าน)
      • 'Ozone'/'โอโซน' → ใช้ค่าที่ได้ full membership=1.0
                          จากฟัซซี่ (เฉพาะคอลัมน์ Cl2)
      • '-' / ''        → None (ไม่วัด)
      • ข้ามแถว 'มาตรฐาน' และ 'หมายเหตุ' (ไม่คำนวณ)

 2) build_hospital_xlsx_report(..)  →  สร้างไฟล์ Excel รายงาน
    เลียนแบบรูปแบบไฟล์จริง (1 ชีต/โรงพยาบาล + ชีต 'กราฟ')
    พร้อมคอลัมน์: สถานะการคำนวณ / Fuzzy Score / ผล / ข้อความ
"""

from __future__ import annotations
import io
import re
import math
from datetime import datetime
from collections import defaultdict

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, NamedStyle
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, LineChart, Reference, RadarChart
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.chart.marker import DataPoint
from openpyxl.chart.trendline import Trendline
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.colors import ColorChoice
from openpyxl.formatting.rule import CellIsRule, FormulaRule, ColorScaleRule
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.header_footer import HeaderFooter

# ============================================================
#  Constants
# ============================================================
# รายการคอลัมน์พารามิเตอร์ที่ระบบรู้จัก (ตรงกับฐานข้อมูล)
PARAM_COLS = ['pH', 'BOD', 'COD', 'TSS', 'TDS', 'O&G', 'TKN',
              'Sulfide', 'NH4', 'TCB', 'FCB', 'Cl2', 'DO']

# โทนสีของเอกสาร (Hex ไม่มี #)
CLR = {
    'header_bg':  '1E3A8A',   # น้ำเงินเข้ม (navy)
    'header_fg':  'FFFFFF',
    'subheader':  '3B5CA8',
    'std_bg':     'FFF3CD',   # เหลืองอ่อน สำหรับแถวมาตรฐาน
    'note_bg':    'F1F5F9',
    'pass':       '16A34A',
    'near':       'F59E0B',
    'fail':       'DC2626',
    'grid':       'CBD5E1',
    'soft':       'F8FAFC',
}

# หน่วยของแต่ละพารามิเตอร์ (ใช้ใน chart titles และ axis labels)
PARAM_UNITS = {
    'pH':      '',          # pH ไม่มีหน่วย
    'BOD':     'mg/L',
    'COD':     'mg/L',
    'TSS':     'mg/L',
    'TDS':     'mg/L',
    'O&G':     'mg/L',
    'TKN':     'mg/L',
    'Sulfide': 'mg/L',
    'NH4':     'mg/L',
    'TCB':     'MPN/100mL',
    'FCB':     'MPN/100mL',
    'Cl2':     'mg/L',
    'DO':      'mg/L',
}

# ป้ายพารามิเตอร์ (header แถวที่ 3 ของไฟล์จริง)
HEADER_LABELS = {
    'pH':      'pH',
    'BOD':     'BOD\nmg/L',
    'COD':     'COD\nmg/L',
    'TSS':     'TSS\nmg/L',
    'TDS':     'TDS\nmg/L',
    'O&G':     'O&G\nmg/L',
    'TKN':     'TKN\nmg/L',
    'Sulfide': 'Sulfide\nmg/L',
    'NH4':     'NH+4\nmg/L',
    'TCB':     'TCB\nMPN/100 ml',
    'FCB':     'FCB\nMPN/100 ml',
    'Cl2':     'Cl2\nmg/L',
    'DO':      'DO\nmg/L',
}

# แผนที่ชื่อคอลัมน์ (เมื่ออ่านจากไฟล์จริง) → คอลัมน์มาตรฐาน
HEADER_ALIAS = {
    'ph':      'pH',
    'bod':     'BOD',
    'cod':     'COD',
    'tss':     'TSS',
    'tds':     'TDS',
    'o&g':     'O&G',
    'og':      'O&G',
    'o_g':     'O&G',
    'oandg':   'O&G',
    'tkn':     'TKN',
    'sulfide': 'Sulfide',
    'nh+4':    'NH4',
    'nh4':     'NH4',
    'nh4+':    'NH4',
    'tcb':     'TCB',
    'fcb':     'FCB',
    'cl2':     'Cl2',
    'chlorine':'Cl2',
    'do':      'DO',
}

# ค่าข้อความที่ต้องการแปลง (lower)
TOKEN_NOT_FOUND = {'ไม่พบ', 'not detected', 'nd', 'none', 'ไม่มี'}
TOKEN_OZONE     = {'ozone', 'โอโซน', 'o3'}
TOKEN_NO_DATA   = {'-', '–', '—', 'n/a', 'na', ''}

# เดือนไทยแบบย่อ (ใช้แปลง date 'dd เดือน ปี')
TH_MONTH_SHORT = {
    'ม.ค.': 1, 'ม.ค':1, 'มค':1, 'ม ค':1,
    'ก.พ.': 2, 'ก.พ':2, 'กพ':2,
    'มี.ค.':3, 'มี.ค':3, 'มีค':3,
    'เม.ย.':4, 'เม.ย':4, 'เมย':4,
    'พ.ค.': 5, 'พ.ค':5, 'พค':5,
    'มิ.ย.':6, 'มิ.ย':6, 'มิย':6,
    'ก.ค.': 7, 'ก.ค':7, 'กค':7,
    'ส.ค.': 8, 'ส.ค':8, 'สค':8,
    'ก.ย.': 9, 'ก.ย':9, 'กย':9,
    'ต.ค.': 10,'ต.ค':10,'ตค':10,
    'พ.ย.': 11,'พ.ย':11,'พย':11,
    'ธ.ค.': 12,'ธ.ค':12,'ธค':12,
}

# ============================================================
#  Utilities
# ============================================================
def _norm_key(k) -> str:
    if k is None: return ''
    s = str(k).strip().lower()
    s = s.replace('\n', ' ').replace('\r', ' ')
    s = re.sub(r'\s+', ' ', s)
    s = s.replace(' ', '')
    return s


def _is_blank(v) -> bool:
    if v is None: return True
    if isinstance(v, str) and v.strip() == '': return True
    try:
        return pd.isna(v)
    except Exception:
        return False


def _parse_thai_date(text):
    """'18 มี.ค. 67' → datetime(2024, 3, 18)
       รองรับปี พ.ศ. (เช่น 67, 2567) และ ค.ศ. (2024)
    """
    if _is_blank(text): return None
    s = str(text).strip()

    # ลองรูปแบบ pandas ก่อน (เผื่อเป็น datetime จริง)
    try:
        d = pd.to_datetime(s, errors='raise')
        if not pd.isna(d):
            return d.to_pydatetime()
    except Exception:
        pass

    # รูปแบบไทย: '18 มี.ค. 67'
    m = re.match(r'^\s*(\d{1,2})\s+([ก-๙\.\s]+?)\s+(\d{2,4})\s*$', s)
    if m:
        day, mon_th, year = m.group(1), m.group(2).strip(), m.group(3)
        mon = None
        k = mon_th.replace(' ', '')
        for key, val in TH_MONTH_SHORT.items():
            if key.replace(' ', '') == k or key in mon_th:
                mon = val; break
        if mon:
            y = int(year)
            if y < 100: y += 2500            # 67 → 2567
            if y > 2400: y -= 543            # พ.ศ. → ค.ศ.
            try:
                return datetime(y, mon, int(day))
            except ValueError:
                return None

    # รูปแบบ dd/mm/yyyy พ.ศ.
    m = re.match(r'^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$', s)
    if m:
        d, mm, y = map(int, m.groups())
        if y < 100: y += 2500
        if y > 2400: y -= 543
        try:
            return datetime(y, mm, d)
        except ValueError:
            return None
    return None


# ============================================================
#  Cl2 substitute value for "Ozone" treatment
# ------------------------------------------------------------
#  โรงพยาบาลที่ใช้ Ozone ไม่ได้ใส่คลอรีน → วัด Cl2 ไม่ได้จริง
#  แต่มีการฆ่าเชื้อเกิดขึ้น (ไม่ใช่ "ไม่มีการฆ่าเชื้อ") จึงต้องแทนค่า
#
#  เลือก Cl2 = 1.0 mg/L เพราะ:
#    1) อยู่ขอบล่างของ normal_core plateau [0.80, 4.0] → μ=1.0
#       (ผ่านแบบเต็มคะแนน แต่ไม่ใช่ "optimal" แบบกึ่งกลาง 2.4)
#    2) ตรงกับ max=1.0 ของมาตรฐาน Cl2 ในเอกสารกำกับจริง
#       → defensible ต่อผู้ตรวจสอบ (ไม่ได้เลือกเพื่อ optimize score)
#    3) ตัวเลขกลม อธิบายง่าย เขียน audit trail สะดวก
#    4) ไม่กลบพารามิเตอร์อื่น — ถ้า BOD/COD พังก็ยัง Fail โดยรวม
# ============================================================
CL2_OZONE_SUBSTITUTE = 1.0


def _cl2_ozone_value(fuzzy_system=None) -> float:
    """คืนค่าที่ใช้แทน 'Ozone' ในคอลัมน์ Cl2 (mg/L)

    ค่าคงที่ 1.0 ได้รับเลือกด้วยเหตุผลเชิงวิชาการ (ดูบล็อกคอมเมนต์ด้านบน)
    fuzzy_system เก็บไว้เป็นพารามิเตอร์เผื่ออนาคตต้องคำนวณแบบ dynamic
    """
    return CL2_OZONE_SUBSTITUTE


def convert_cell_value(raw, col_name: str, fuzzy_system=None):
    """แปลงค่าจากเซลล์เป็นตัวเลข (หรือ None) ตามกฎด้านบน

    Returns tuple (value, note) where note อธิบายว่าเกิด substitution อะไร
    """
    if _is_blank(raw):
        return None, None

    # ตัวเลขตรง ๆ
    if isinstance(raw, (int, float)) and not (isinstance(raw, float) and math.isnan(raw)):
        return float(raw), None

    s = str(raw).strip()
    low = s.lower()

    # ค่าที่เก็บเป็นสตริงแต่จริง ๆ เป็นตัวเลข เช่น "1,600" หรือ "12.5"
    cleaned = s.replace(',', '').replace(' ', '')
    try:
        return float(cleaned), None
    except ValueError:
        pass

    # ไม่พบ / ND → 0
    if low in TOKEN_NOT_FOUND or any(t in low for t in TOKEN_NOT_FOUND):
        return 0.0, 'ไม่พบ→0'

    # Ozone (เฉพาะ Cl2) → แทนค่าด้วย 1.0 mg/L (ดูคอมเมนต์ที่ CL2_OZONE_SUBSTITUTE)
    if low in TOKEN_OZONE or any(t in low for t in TOKEN_OZONE):
        if col_name == 'Cl2':
            v = _cl2_ozone_value(fuzzy_system)
            return v, f'Ozone→{v} mg/L (ขอบล่าง plateau = มาตรฐานสูงสุด)'
        # คอลัมน์อื่นไม่ make sense → ไม่แปลง
        return None, 'Ozone (ไม่ใช่ Cl2) → ข้าม'

    # '-' '–' ฯลฯ = ไม่วัด
    if low in TOKEN_NO_DATA:
        return None, None

    # ข้อความอื่น ๆ ที่ไม่เข้าใจ
    return None, f'อ่านค่าไม่ได้: {s!r}'


# ============================================================
#  Detector & Reader
# ============================================================
def _is_hospital_format(wb) -> bool:
    """คืน True ถ้าไฟล์เป็นรูปแบบ "ต่อโรงพยาบาล"
       หลักการ: ชีตแรกมีคำว่า 'วัน/เดือน/ปี' หรือ 'พารามิเตอร์' ใน 5 แถวแรก
    """
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(min_row=1, max_row=6, values_only=True):
            for v in row:
                if isinstance(v, str) and (
                    'วัน/เดือน/ปี' in v or 'พารามิเตอร์' in v
                    or 'ตำแหน่งที่ทำการวิเคราะห์' in v
                ):
                    return True
        # ชีตแรกพอแล้ว
        break
    return False


def _read_hospital_sheet(ws, fuzzy_system=None):
    """อ่านชีตเดียวในรูปแบบโรงพยาบาล → list[dict] พร้อม note ของ substitution

    คืนค่า (rows, notes) โดย rows เป็น dict มีคีย์เท่ากับ flat format
    """
    max_row = min(ws.max_row, 200)    # ไฟล์จริงมักมีข้อมูลน้อย
    max_col = min(ws.max_column, 30)

    # ดึงเป็น list[list]
    grid = []
    for r in ws.iter_rows(min_row=1, max_row=max_row,
                          max_col=max_col, values_only=True):
        grid.append(list(r))

    # หา header row (แถวที่มีคำว่า 'pH') ในช่วง 10 แถวแรก
    header_row = None
    for i, row in enumerate(grid[:10]):
        for v in row:
            if isinstance(v, str) and v.strip().lower().startswith('ph'):
                header_row = i; break
        if header_row is not None: break
    if header_row is None:
        return [], []

    # สร้าง column map: index → standard column
    col_map = {}
    for j, v in enumerate(grid[header_row]):
        if _is_blank(v): continue
        key = _norm_key(v.split('\n')[0] if isinstance(v, str) else v)
        key = key.replace('/', '')
        std = HEADER_ALIAS.get(key)
        if std: col_map[j] = std

    if not col_map:
        return [], []

    # คอลัมน์ date / location ตามโครงสร้างไฟล์ = col A / col B
    rows = []
    notes = []
    for i in range(header_row + 1, len(grid)):
        row = grid[i]
        first = row[0] if len(row) > 0 else None
        # ข้ามแถว 'มาตรฐาน' และ 'หมายเหตุ'
        if isinstance(first, str):
            ft = first.strip()
            if ft.startswith('มาตรฐาน') or ft.startswith('หมายเหตุ'):
                continue
            if 'ไม่ได้ทำการตรวจวิเคราะห์' in ft:
                continue

        date = _parse_thai_date(first)
        if date is None:
            # อาจเป็นแถวว่าง หรือหมายเหตุต่อท้าย → ข้าม
            continue

        pond = row[1] if len(row) > 1 else None
        pond = str(pond).strip() if not _is_blank(pond) else 'บ่อพักน้ำทิ้ง'

        rec = {
            'sample_date':     date,
            'pond_name':       pond,
            'sample_type':     'หลังบำบัด',   # ระบบจริงเป็นน้ำทิ้ง
        }
        for j, col in col_map.items():
            raw = row[j] if j < len(row) else None
            val, note = convert_cell_value(raw, col, fuzzy_system=fuzzy_system)
            rec[col] = val
            if note:
                notes.append({
                    'row':  i + 1,
                    'col':  col,
                    'raw':  raw,
                    'note': note,
                })
        rows.append(rec)

    return rows, notes


def normalize_hospital_xlsx(file_stream, fuzzy_system=None):
    """อ่านไฟล์ Excel แล้วคืน (DataFrame, notes, fmt)

    fmt = 'hospital'  (รูปแบบไฟล์จริง หลายชีต)  |  'flat' (รูปแบบเดิม)

    ถ้าเป็น hospital จะใช้ชื่อชีตเป็น sample_location
    """
    # เก็บ bytes ก่อนเพราะอ่านสองรอบได้
    if hasattr(file_stream, 'read'):
        data = file_stream.read()
    else:
        with open(file_stream, 'rb') as f:
            data = f.read()

    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=False)

    if _is_hospital_format(wb):
        all_rows = []
        all_notes = []
        for name in wb.sheetnames:
            # ชีต 'กราฟ' คือชีต chart เฉย ๆ ข้าม
            if 'กราฟ' in name or name.strip().lower() == 'graph':
                continue
            ws = wb[name]
            rows, notes = _read_hospital_sheet(ws, fuzzy_system=fuzzy_system)
            loc = name.strip()
            for r in rows:
                r['sample_location'] = loc
            for n in notes:
                n['sheet'] = loc
            all_rows.extend(rows)
            all_notes.extend(notes)
        df = pd.DataFrame(all_rows)
        return df, all_notes, 'hospital'

    # รูปแบบ flat เดิม — อ่านด้วย pandas
    df = pd.read_excel(io.BytesIO(data))
    return df, [], 'flat'


# ============================================================
#  Exporter
# ============================================================
def _thin_border():
    s = Side(border_style='thin', color=CLR['grid'])
    return Border(left=s, right=s, top=s, bottom=s)


def _apply_hdr(cell, bg=CLR['header_bg'], fg=CLR['header_fg'],
               bold=True, size=11):
    cell.font      = Font(name='Tahoma', bold=bold, size=size, color=fg)
    cell.fill      = PatternFill('solid', fgColor=bg)
    cell.alignment = Alignment(horizontal='center', vertical='center',
                               wrap_text=True)
    cell.border    = _thin_border()


def _apply_data(cell, bold=False, color='000000', bg=None, align='center'):
    cell.font      = Font(name='Tahoma', bold=bold, size=10, color=color)
    cell.alignment = Alignment(horizontal=align, vertical='center',
                               wrap_text=True)
    cell.border    = _thin_border()
    if bg:
        cell.fill  = PatternFill('solid', fgColor=bg)


def _setup_page(ws, orientation='landscape', title='', fit_width=1, fit_height=0):
    """ตั้งค่า Page Setup สำหรับ print/PDF: A4, fit-to-page, header/footer
    ป้องกันปัญหาตารางล้นหน้ากระดาษ
    """
    from openpyxl.worksheet.page import PageMargins
    from openpyxl.worksheet.properties import PageSetupProperties

    ws.page_setup.orientation = (ws.ORIENTATION_LANDSCAPE
                                  if orientation == 'landscape'
                                  else ws.ORIENTATION_PORTRAIT)
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth  = fit_width    # fit ทุกคอลัมน์ใน 1 หน้ากว้าง
    ws.page_setup.fitToHeight = fit_height   # 0 = ไม่จำกัดความสูง (ไหลหลายหน้าได้)
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins = PageMargins(left=0.5, right=0.5, top=0.6, bottom=0.6,
                                   header=0.3, footer=0.3)
    ws.print_options.horizontalCentered = True

    # Header/Footer (print preview + PDF)
    ws.oddHeader.center.text  = title or ws.title
    ws.oddHeader.center.size  = 11
    ws.oddHeader.center.color = CLR['header_bg']
    ws.oddFooter.left.text    = '&D &T'              # date + time
    ws.oddFooter.left.size    = 9
    ws.oddFooter.center.text  = 'ระบบประเมินคุณภาพน้ำทิ้งโรงพยาบาล'
    ws.oddFooter.center.size  = 9
    ws.oddFooter.right.text   = 'หน้า &P / &N'      # page x of N
    ws.oddFooter.right.size   = 9


def _write_metadata_block(ws, start_row, location, row_count, date_range,
                          standard_ref='กรมควบคุมมลพิษ พ.ศ. 2566'):
    """เขียน metadata header block 2 แถวสำหรับสื่อถึงอาจารย์/ผู้ตรวจสอบ
    Returns row after block
    """
    from datetime import datetime as _dt
    now = _dt.now().strftime('%d/%m/%Y %H:%M')
    items = [
        ('วันที่ออกรายงาน',  now),
        ('สถานที่',          location or '–'),
        ('จำนวนครั้งตรวจ',   f'{row_count} ครั้ง'),
        ('ช่วงวันที่ข้อมูล', date_range or '–'),
        ('มาตรฐานอ้างอิง',   standard_ref),
    ]
    for i, (k, v) in enumerate(items):
        r = start_row + (i // 2)
        c = (i % 2) * 3 + 1   # columns 1,4 alternating
        kc = ws.cell(row=r, column=c,     value=k)
        vc = ws.cell(row=r, column=c + 1, value=str(v))
        kc.font = Font(name='Tahoma', bold=True, size=9, color='475569')
        vc.font = Font(name='Tahoma', bold=False, size=9, color='0F172A')
        kc.alignment = Alignment(horizontal='right', vertical='center', indent=1)
        vc.alignment = Alignment(horizontal='left',  vertical='center', indent=1)
        kc.fill = PatternFill('solid', fgColor=CLR['note_bg'])
        vc.fill = PatternFill('solid', fgColor=CLR['note_bg'])
    ws.row_dimensions[start_row].height     = 18
    ws.row_dimensions[start_row + 1].height = 18
    ws.row_dimensions[start_row + 2].height = 18
    return start_row + 3


def _set_chart_title_top(chart):
    """บังคับให้ title ของ chart อยู่ด้านบน ไม่ทับกับ plot area
    แก้ปัญหา title ลอยมาอยู่ที่เส้นข้อมูลแทนที่จะอยู่บนสุด
    """
    if chart.title is not None:
        # บังคับ overlay=False เพื่อให้ title แยกออกมาจากพื้นที่ plot
        chart.title.overlay = False


def _compute_stats(values):
    """คำนวณสถิติพื้นฐานจาก list ของค่า (ข้าม None)"""
    import statistics as st
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {'n': 0, 'mean': None, 'sd': None, 'min': None,
                'max': None, 'median': None}
    return {
        'n':      len(vals),
        'mean':   sum(vals) / len(vals),
        'sd':     st.stdev(vals) if len(vals) > 1 else 0.0,
        'min':    min(vals),
        'max':    max(vals),
        'median': st.median(vals),
    }


def _status_th(s):
    return {'Pass': 'ผ่านมาตรฐาน', 'Near Limit': 'เฝ้าระวัง',
            'Fail': 'เกินมาตรฐาน', 'No Data': 'ไม่มีข้อมูล'}.get(s, '–')


def _status_color(s):
    return {'Pass': CLR['pass'], 'Near Limit': CLR['near'],
            'Fail': CLR['fail']}.get(s, '475569')


def _fmt_num(v, nd=2):
    if v is None: return '–'
    try:
        f = float(v)
        if math.isinf(f) or math.isnan(f): return '–'
        return f'{f:,.{nd}f}' if f != int(f) else f'{int(f):,}'
    except Exception:
        return str(v)


def _fmt_date(d):
    if d is None: return '–'
    try:
        return d.strftime('%d/%m/%Y')
    except Exception:
        return str(d)


def _row_building_type(row, default='ก'):
    """ดึง building_type จาก row (รองรับทั้ง attribute และ dict)"""
    bt = getattr(row, 'building_type', None)
    if not bt:
        try:
            bt = row.get('building_type', default)
        except Exception:
            bt = default
    return (bt or default).strip() or default

def _std_for_row(row, std_key, standards_by_type=None, default_standards=None, default_bt='ก'):
    """หาค่ามาตรฐานของ parameter สำหรับ row นี้ (อิงจาก building_type)
    คืน dict {'min':...,'max':...} หรือ None ถ้าไม่กำหนด"""
    if not std_key:
        return None
    bt = _row_building_type(row, default_bt)
    if standards_by_type and bt in standards_by_type:
        std = standards_by_type[bt].get(std_key)
        if std is None:  # explicit ไม่กำหนด
            return None
        return std
    # fallback
    if default_standards:
        return default_standards.get(std_key)
    return None

def _format_std(std):
    """แปลง std dict → text เช่น '≤ 20' หรือ '5.0–9.0' หรือ 'ไม่กำหนด'"""
    if std is None:
        return 'ไม่กำหนด'
    if not isinstance(std, dict):
        return '–'
    mn, mx = std.get('min'), std.get('max')
    if mn is not None and mx is not None:
        return f'{mn}–{mx}'
    if mx is not None:
        try:
            return f'≤ {mx:,}' if mx >= 1000 else f'≤ {mx}'
        except Exception:
            return f'≤ {mx}'
    if mn is not None:
        return f'≥ {mn}'
    return '–'

def _predominant_bt(rows, default='ก'):
    """หา building_type ที่พบมากที่สุดในกลุ่ม rows"""
    from collections import Counter
    bts = [_row_building_type(r, default) for r in rows]
    if not bts:
        return default
    return Counter(bts).most_common(1)[0][0]

def _building_types_in(rows, default='ก'):
    """list ของ building_type ที่ unique"""
    return sorted({_row_building_type(r, default) for r in rows})


def _build_hospital_sheet(wb, sheet_name, location, rows_raw,
                          fuzzy_system=None,
                          build_parameters=None,
                          can_fuzzy_eval=None,
                          score_to_overall_status=None,
                          standards=None,
                          get_fuzzy_system=None,
                          default_building_type='ก',
                          standards_by_type=None):
    """สร้างชีต 1 โรงพยาบาล (mimic รูปแบบไฟล์จริง)
       rows_raw: list ของ WaterQualityData หรือ dict-like (ต้องมี attributes)
       get_fuzzy_system: callable(building_type) -> fuzzy_system (ใช้ fuzzy ตามประเภทอาคารของแต่ละ row)
    """
    ws = wb.create_sheet(title=sheet_name[:31])

    # ==== Row 1: Title / Location name ====
    ws.merge_cells('A1:R1')
    c = ws['A1']
    c.value = f'ผลตรวจวิเคราะห์คุณภาพน้ำทิ้ง — {location}'
    c.font  = Font(name='Tahoma', bold=True, size=13, color=CLR['header_fg'])
    c.fill  = PatternFill('solid', fgColor=CLR['header_bg'])
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 26

    # ==== Row 2-3: Header (merged like the real file) ====
    ws.merge_cells('A2:A3'); ws['A2'] = 'วัน/เดือน/ปี'
    ws.merge_cells('B2:B3'); ws['B2'] = 'ตำแหน่งที่ทำการวิเคราะห์'
    last_param_col = 2 + len(PARAM_COLS)
    ws.merge_cells(start_row=2, start_column=3,
                   end_row=2, end_column=last_param_col)
    ws.cell(row=2, column=3).value = 'พารามิเตอร์ที่ทำการวิเคราะห์'

    # Extra header cells for result columns (เพิ่ม "อาคาร" ก่อนสถานะการคำนวณ)
    extra_headers = ['อาคาร', 'สถานะการคำนวณ', 'คะแนนสุดท้าย\n(Fuzzy 0-100)', 'ผล', 'ข้อความ']
    col_extra_start = last_param_col + 1
    for i, h in enumerate(extra_headers):
        ws.merge_cells(start_row=2, start_column=col_extra_start + i,
                       end_row=3,   end_column=col_extra_start + i)
        ws.cell(row=2, column=col_extra_start + i).value = h

    # sub-headers row 3 (params)
    for i, key in enumerate(PARAM_COLS):
        ws.cell(row=3, column=3 + i).value = HEADER_LABELS[key]

    # Apply header styles
    for row in (2, 3):
        for col in range(1, col_extra_start + len(extra_headers)):
            cell = ws.cell(row=row, column=col)
            _apply_hdr(cell)
    ws.row_dimensions[2].height = 22
    ws.row_dimensions[3].height = 34

    # ==== Data rows ====
    r = 4
    results_for_chart = []   # สำหรับใช้ในชีตกราฟ
    pass_c = near_c = fail_c = nodata_c = 0
    for wd in rows_raw:
        date = getattr(wd, 'sample_date', None)
        pond = getattr(wd, 'pond_name', None) or 'บ่อพักน้ำทิ้ง'

        ws.cell(row=r, column=1).value = _fmt_date(date)
        ws.cell(row=r, column=2).value = pond

        param_values = {
            'pH':  getattr(wd, 'pH', None),
            'BOD': getattr(wd, 'BOD', None),
            'COD': getattr(wd, 'COD', None),
            'TSS': getattr(wd, 'TSS', None),
            'TDS': getattr(wd, 'TDS', None),
            'O&G': getattr(wd, 'oil_grease', None),
            'TKN': getattr(wd, 'TKN', None),
            'Sulfide': getattr(wd, 'sulfide', None),
            'NH4': getattr(wd, 'ammonium', None),
            'TCB': getattr(wd, 'TCB', None),
            'FCB': getattr(wd, 'FCB', None),
            'Cl2': getattr(wd, 'chlorine', None),
            'DO':  getattr(wd, 'dissolved_oxygen', None),
        }
        for i, key in enumerate(PARAM_COLS):
            v = param_values.get(key)
            cell = ws.cell(row=r, column=3 + i)
            cell.value = v if v is not None else '-'

        # building_type ของ row นี้
        row_bt = (getattr(wd, 'building_type', None) or default_building_type).strip()

        # Fuzzy evaluation
        calc_status = 'ข้อมูลไม่ครบ'
        score = None
        result_th = '–'
        message  = ''
        status_en = 'No Data'

        # ใช้ fuzzy_system ของประเภทอาคารนั้น ๆ ถ้ามี get_fuzzy_system
        _fs_for_row = (get_fuzzy_system(row_bt) if get_fuzzy_system else fuzzy_system)
        if build_parameters and can_fuzzy_eval and _fs_for_row:
            params = build_parameters(wd)
            if can_fuzzy_eval(params):
                try:
                    ev  = _fs_for_row.evaluate_overall(params)
                    score = ev.get('overall_score')
                    message = ev.get('overall_message', '')
                    if score is not None:
                        status_en = score_to_overall_status(score) \
                                    if score_to_overall_status else 'No Data'
                        calc_status = 'คำนวณสำเร็จ'
                        result_th   = _status_th(status_en)
                except Exception as e:
                    calc_status = f'ผิดพลาด: {type(e).__name__}'
            else:
                calc_status = 'ข้อมูลไม่ครบ'

        # Write extras (อาคาร, สถานะ, คะแนน, ผล, ข้อความ)
        ws.cell(row=r, column=col_extra_start).value       = row_bt
        ws.cell(row=r, column=col_extra_start + 1).value   = calc_status
        ws.cell(row=r, column=col_extra_start + 2).value   = round(score, 1) if score is not None else '–'
        ws.cell(row=r, column=col_extra_start + 3).value   = result_th
        ws.cell(row=r, column=col_extra_start + 4).value   = message or '–'

        # styles
        for col in range(1, col_extra_start + len(extra_headers)):
            cell = ws.cell(row=r, column=col)
            _apply_data(cell, align='center' if col > 2 else 'center')

        # Color result column (เลื่อนเพราะมี 'อาคาร' เพิ่ม → result อยู่ที่ +3)
        rc = ws.cell(row=r, column=col_extra_start + 3)
        rc.font = Font(name='Tahoma', bold=True, size=10,
                       color=_status_color(status_en))
        # Color score column (อยู่ที่ +2)
        sc = ws.cell(row=r, column=col_extra_start + 2)
        sc.font = Font(name='Tahoma', bold=True, size=10,
                       color=_status_color(status_en))
        # Color building_type column (อยู่ที่ +0) — น้ำเงินเข้มให้สังเกตง่าย
        bc = ws.cell(row=r, column=col_extra_start)
        bc.font = Font(name='Tahoma', bold=True, size=10, color='1E3A8A')

        # Tally
        if status_en == 'Pass':       pass_c += 1
        elif status_en == 'Near Limit': near_c += 1
        elif status_en == 'Fail':     fail_c += 1
        else:                         nodata_c += 1

        # Collect for chart
        results_for_chart.append({
            'date':   _fmt_date(date),
            'pond':   pond,
            'params': param_values,
            'status': status_en,
            'score':  score,
        })

        r += 1

    # ==== Row: มาตรฐาน (ไม่คำนวน, สีเหลืองอ่อน) ====
    # ใช้ปะรเภทอาคารที่พบมากที่สุดในกลุ่ม rows
    # ถ้ามีหลายประเภท จะเขียนหมายเหตุไว้
    std_row = r
    std_cell = ws.cell(row=std_row, column=1)
    bt_list = _building_types_in(rows_raw, default=default_building_type)
    bt_primary = _predominant_bt(rows_raw, default=default_building_type)
    if len(bt_list) > 1:
        std_cell.value = f'มาตรฐาน (อาคาร {bt_primary} - ส่วนใหญ่)'
    else:
        std_cell.value = f'มาตรฐาน (อาคาร {bt_primary})'
    ws.cell(row=std_row, column=2).value = '-'

    # ใช้มาตรฐานของอาคาร bt_primary
    if standards_by_type and bt_primary in standards_by_type:
        active_standards = standards_by_type[bt_primary]
    else:
        active_standards = standards or {}

    std_map = {}
    for key in PARAM_COLS:
        std_value = active_standards.get(key) if key in active_standards else None
        std_map[key] = _format_std(std_value)
    # NH4, DO ไม่อยู่ในมาตรฐาน → ใส่ –
    std_map.setdefault('NH4', '–')
    std_map.setdefault('DO', '–')

    for i, key in enumerate(PARAM_COLS):
        ws.cell(row=std_row, column=3 + i).value = std_map.get(key, '–')

    ws.cell(row=std_row, column=col_extra_start).value     = '–'
    ws.cell(row=std_row, column=col_extra_start + 1).value = '–'
    ws.cell(row=std_row, column=col_extra_start + 2).value = '–'
    ws.cell(row=std_row, column=col_extra_start + 3).value = '–'
    note = 'อ้างอิง: ประกาศ ก.ทรัพยากรธรรมชาติฯ พ.ศ. 2567'
    if len(bt_list) > 1:
        note += f' (พบหลายประเภทอาคาร: {", ".join(bt_list)} - แสดงของ {bt_primary})'
    ws.cell(row=std_row, column=col_extra_start + 4).value = note

    for col in range(1, col_extra_start + len(extra_headers)):
        cell = ws.cell(row=std_row, column=col)
        _apply_data(cell, bold=True, bg=CLR['std_bg'])
    r += 1

    # ==== Row: สรุปผล ====
    total = pass_c + near_c + fail_c + nodata_c
    summary_row = r + 1
    ws.cell(row=summary_row, column=1).value = 'สรุป'
    cnt_txt = (f'ตรวจวัดทั้งหมด {total} ครั้ง  |  '
               f'ผ่าน {pass_c}  ·  เฝ้าระวัง {near_c}  ·  '
               f'เกินมาตรฐาน {fail_c}  ·  ไม่มีข้อมูล {nodata_c}')
    ws.merge_cells(start_row=summary_row, start_column=2,
                   end_row=summary_row,   end_column=col_extra_start + len(extra_headers) - 1)
    ws.cell(row=summary_row, column=2).value = cnt_txt
    for col in range(1, col_extra_start + len(extra_headers)):
        cell = ws.cell(row=summary_row, column=col)
        _apply_data(cell, bold=True, bg=CLR['note_bg'], align='left' if col > 1 else 'center')

    # ==== Row: หมายเหตุ ====
    note_row = summary_row + 1
    ws.cell(row=note_row, column=1).value = 'หมายเหตุ'
    note_txt = ('"ไม่พบ" → แทนค่าเป็น 0  |  '
                '"Ozone" → แทนค่า Cl2 = 1.0 mg/L (ขอบล่างของโซนผ่านฟัซซี่ / '
                'ตรงกับมาตรฐานสูงสุด Cl2)  |  '
                '"-" → ไม่ได้วัด (ระบบจะไม่คำนวณแถวที่ข้อมูลไม่ครบ)')
    ws.merge_cells(start_row=note_row, start_column=2,
                   end_row=note_row,   end_column=col_extra_start + len(extra_headers) - 1)
    ws.cell(row=note_row, column=2).value = note_txt
    for col in range(1, col_extra_start + len(extra_headers)):
        cell = ws.cell(row=note_row, column=col)
        _apply_data(cell, bold=False, bg=CLR['note_bg'],
                    align='left' if col > 1 else 'center')

    # ==== Column widths ====
    ws.column_dimensions['A'].width = 14
    ws.column_dimensions['B'].width = 22
    for i, _ in enumerate(PARAM_COLS):
        col_letter = get_column_letter(3 + i)
        ws.column_dimensions[col_letter].width = 12
    for i, _ in enumerate(extra_headers):
        col_letter = get_column_letter(col_extra_start + i)
        # i = 0:อาคาร(8), 1:สถานะการคำนวณ(16), 2:คะแนน(13), 3:ผล(12), 4:ข้อความ(38)
        widths = [8, 16, 13, 12, 38]
        ws.column_dimensions[col_letter].width = widths[i] if i < len(widths) else 16

    # freeze top
    ws.freeze_panes = 'A4'

    # ── Conditional formatting: ค่าเกินมาตรฐาน → สีแดงอ่อน ─────
    # หาข้อมูล data rows (row 4 ถึง r-1 เฉพาะแถวข้อมูล ไม่รวม มาตรฐาน/สรุป/หมายเหตุ)
    if std_row > 4:
        data_last_row = std_row - 1
        # กำหนด fill แดงอ่อนสำหรับเซลล์เกินมาตรฐาน
        fail_fill = PatternFill('solid', fgColor='FEE2E2')

        # ใช้ active_standards (อาคารที่พบมากที่สุด) — ถ้ามีหลายประเภท ก็ใช้ของอาคารหลัก
        # หมายเหตุ: Excel conditional formatting ใช้ rule เดียวต่อ column → ไม่สามารถใช้ standard
        # ต่างกันต่อ row ได้ ผู้ใช้ดูที่ column "ผล" ใน sheet เพื่อความถูกต้องของแต่ละ row
        def _maxv(key):
            s = active_standards.get(key) if active_standards else None
            return s.get('max') if isinstance(s, dict) else None
        def _minv(key):
            s = active_standards.get(key) if active_standards else None
            return s.get('min') if isinstance(s, dict) else None

        PARAM_COL_MAP = {
            'pH':      (3,  _maxv('pH'),      _minv('pH')),
            'BOD':     (4,  _maxv('BOD'),     None),
            'COD':     (5,  _maxv('COD'),     None),
            'TSS':     (6,  _maxv('TSS'),     None),
            'TDS':     (7,  _maxv('TDS'),     None),
            'O&G':     (8,  _maxv('O&G'),     None),
            'TKN':     (9,  _maxv('TKN'),     None),
            'Sulfide': (10, _maxv('Sulfide'), None),
            'NH4':     (11, None, None),
            'TCB':     (12, _maxv('TCB'),     None),
            'FCB':     (13, _maxv('FCB'),     None),
            'Cl2':     (14, _maxv('Cl2'),     _minv('Cl2')),
            'DO':      (15, None, None),
        }

        for pname, (col_idx, std_max, std_min) in PARAM_COL_MAP.items():
            if std_max is None and std_min is None:
                continue
            col_letter = get_column_letter(col_idx)
            cell_range = f'{col_letter}4:{col_letter}{data_last_row}'
            # สูงกว่า max
            if std_max is not None:
                ws.conditional_formatting.add(
                    cell_range,
                    CellIsRule(operator='greaterThan', formula=[str(std_max)],
                               fill=fail_fill)
                )
            # ต่ำกว่า min (สำหรับ pH, Cl2)
            if std_min is not None:
                ws.conditional_formatting.add(
                    cell_range,
                    CellIsRule(operator='lessThan', formula=[str(std_min)],
                               fill=fail_fill)
                )

    # ── Page setup ────────────────────────────────────────
    _setup_page(ws, orientation='landscape',
                title=f'ผลตรวจวิเคราะห์ — {location}')

    return results_for_chart, {'pass': pass_c, 'near': near_c,
                                'fail': fail_c, 'nodata': nodata_c,
                                'total': total}


def _build_statistics_sheet(wb, hospitals_rows, standards=None, standards_by_type=None, default_building_type='ก'):
    """ชีต 'สถิติสรุป' — ค่าเฉลี่ย/SD/min/max/median ต่อพารามิเตอร์ต่อ รพ.
    (สำคัญสำหรับอาจารย์ใช้เขียนบทความวิจัย)
    มาตรฐานที่แสดงจะอิงตามประเภทอาคารที่พบมากที่สุดในแต่ละกลุ่ม
    """
    ws = wb.create_sheet(title='สถิติสรุป')

    # Title
    ws.merge_cells('A1:I1')
    c = ws['A1']
    c.value = 'สถิติสรุปรายพารามิเตอร์ต่อโรงพยาบาล (Descriptive Statistics)'
    c.font  = Font(name='Tahoma', bold=True, size=14, color=CLR['header_fg'])
    c.fill  = PatternFill('solid', fgColor=CLR['header_bg'])
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    PARAMS_FIELDS = [
        ('pH', 'pH', 'pH'),
        ('BOD', 'BOD', 'BOD'),
        ('COD', 'COD', 'COD'),
        ('TSS', 'TSS', 'TSS'),
        ('TDS', 'TDS', 'TDS'),
        ('O&G', 'oil_grease', 'O&G'),
        ('TKN', 'TKN', 'TKN'),
        ('Sulfide', 'sulfide', 'Sulfide'),
        ('NH4', 'ammonium', None),
        ('TCB', 'TCB', 'TCB'),
        ('FCB', 'FCB', 'FCB'),
        ('Cl2', 'chlorine', 'Cl2'),
        ('DO', 'dissolved_oxygen', None),
    ]

    cur_row = 3
    for loc, rows in hospitals_rows.items():
        # หา building_type หลักของกลุ่มนี้
        bt_list = _building_types_in(rows, default=default_building_type)
        bt_primary = _predominant_bt(rows, default=default_building_type)
        if standards_by_type and bt_primary in standards_by_type:
            active_standards = standards_by_type[bt_primary]
        else:
            active_standards = standards or {}

        # Section header (เพิ่มข้อมูลประเภทอาคาร)
        ws.merge_cells(start_row=cur_row, start_column=1,
                       end_row=cur_row,   end_column=9)
        s = ws.cell(row=cur_row, column=1)
        bt_text = f'อาคาร {bt_primary}' if len(bt_list) == 1 else f'อาคาร {bt_primary} (หลัก) + {",".join([b for b in bt_list if b != bt_primary])}'
        s.value = f'📊 {loc}  (n = {len(rows)} ครั้ง, {bt_text})'
        s.font  = Font(name='Tahoma', bold=True, size=12, color='FFFFFF')
        s.fill  = PatternFill('solid', fgColor=CLR['subheader'])
        s.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws.row_dimensions[cur_row].height = 22
        cur_row += 1

        # Headers
        headers = ['พารามิเตอร์', 'หน่วย', 'n', 'ค่าเฉลี่ย\n(Mean)',
                   'ส่วนเบี่ยงเบน\n(SD)', 'ต่ำสุด\n(Min)',
                   'สูงสุด\n(Max)', 'มัธยฐาน\n(Median)', f'มาตรฐาน\n(อาคาร {bt_primary})']
        for i, h in enumerate(headers):
            _apply_hdr(ws.cell(row=cur_row, column=1 + i, value=h))
        ws.row_dimensions[cur_row].height = 32
        cur_row += 1

        # Data rows per param
        UNITS = {'pH':'–','BOD':'mg/L','COD':'mg/L','TSS':'mg/L','TDS':'mg/L',
                 'O&G':'mg/L','TKN':'mg/L','Sulfide':'mg/L','NH4':'mg/L',
                 'TCB':'MPN/100mL','FCB':'MPN/100mL','Cl2':'mg/L','DO':'mg/L'}

        for disp_name, attr, std_key in PARAMS_FIELDS:
            values = [getattr(w, attr, None) for w in rows]
            stats = _compute_stats(values)

            # Standard text — ใช้ active_standards (อิงจาก bt_primary)
            std_str = _format_std(active_standards.get(std_key)) if std_key else '–'

            vals = [
                disp_name, UNITS.get(disp_name, '–'), stats['n'],
                _fmt_num(stats['mean']), _fmt_num(stats['sd']),
                _fmt_num(stats['min']),  _fmt_num(stats['max']),
                _fmt_num(stats['median']), std_str,
            ]
            for i, v in enumerate(vals):
                cell = ws.cell(row=cur_row, column=1 + i, value=v)
                _apply_data(cell, bold=(i == 0),
                            align='left' if i == 0 else 'center')
                if i == 8:  # standards col — yellow tint
                    cell.fill = PatternFill('solid', fgColor=CLR['std_bg'])
            cur_row += 1
        cur_row += 1   # spacer between hospitals

    # Column widths
    widths = [13, 11, 6, 12, 12, 11, 11, 12, 18]
    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(1 + i)].width = w

    _setup_page(ws, orientation='portrait',
                title='สถิติสรุปรายพารามิเตอร์')


def _build_trend_sheet(wb, hospitals_data, standards=None, hospitals_rows=None,
                       standards_by_type=None, default_building_type='ก'):
    """ชีต 'แนวโน้ม' — Time-series line charts สำหรับทุกพารามิเตอร์
    (BOD, COD, TSS, Cl2, pH) ช่วยดูว่าระบบบำบัดดีขึ้น/แย่ลง

    มาตรฐานในกราฟใช้ของอาคารหลักของแต่ละโรงพยาบาล
    ถ้ามีหลายโรงพยาบาลในแนวโน้มเดียวกัน → ใช้ค่ามาตรฐานเข้มสุดเป็นเส้นอ้างอิง
    """
    # หา active_standards (predominant ของทั้งหมด) สำหรับเส้น "มาตรฐานสูงสุด" ในกราฟ
    if standards_by_type and hospitals_rows:
        all_bts = []
        for rows in hospitals_rows.values():
            all_bts.extend(_building_types_in(rows, default=default_building_type))
        if all_bts:
            from collections import Counter
            primary_bt = Counter(all_bts).most_common(1)[0][0]
            active_standards = standards_by_type.get(primary_bt, standards or {})
        else:
            active_standards = standards or {}
            primary_bt = default_building_type
    else:
        active_standards = standards or {}
        primary_bt = default_building_type
    ws = wb.create_sheet(title='แนวโน้ม')

    ws.merge_cells('A1:H1')
    c = ws['A1']
    c.value = 'แนวโน้มคุณภาพน้ำเชิงเวลา (Trend over Time) — ทุกพารามิเตอร์'
    c.font  = Font(name='Tahoma', bold=True, size=14, color=CLR['header_fg'])
    c.fill  = PatternFill('solid', fgColor=CLR['header_bg'])
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    # Union of all dates
    all_dates = []
    for results in hospitals_data.values():
        for r in results:
            if r['date'] != '–' and r['date'] not in all_dates:
                all_dates.append(r['date'])
    all_dates.sort(key=lambda x: (x.split('/')[::-1] if '/' in x else x))
    if not all_dates:
        ws.cell(row=3, column=1, value='ไม่มีข้อมูล')
        return

    # Key parameters for trending
    # ทุกพารามิเตอร์หลักที่ใช้ในการประเมินฟัซซี่ (11 ตัว)
    TREND_PARAMS = ['pH', 'BOD', 'COD', 'TSS', 'TDS', 'O&G',
                    'TKN', 'Sulfide', 'TCB', 'FCB', 'Cl2']

    cur_row = 3
    for param in TREND_PARAMS:
        # Section title
        last_col = 1 + len(all_dates)
        ws.merge_cells(start_row=cur_row, start_column=1,
                       end_row=cur_row, end_column=last_col)
        t = ws.cell(row=cur_row, column=1)
        t.value = f'📈 แนวโน้ม {param} เชิงเวลา'
        t.font = Font(name='Tahoma', bold=True, size=12, color='FFFFFF')
        t.fill = PatternFill('solid', fgColor=CLR['subheader'])
        t.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws.row_dimensions[cur_row].height = 22
        cur_row += 1

        # Header (dates as columns)
        ws.cell(row=cur_row, column=1, value='โรงพยาบาล')
        _apply_hdr(ws.cell(row=cur_row, column=1))
        for j, d in enumerate(all_dates):
            ws.cell(row=cur_row, column=2 + j, value=d)
            _apply_hdr(ws.cell(row=cur_row, column=2 + j))
        header_r = cur_row
        cur_row += 1

        data_start = cur_row
        for hosp, results in hospitals_data.items():
            ws.cell(row=cur_row, column=1, value=hosp)
            _apply_data(ws.cell(row=cur_row, column=1),
                        bold=True, align='left')
            by_date = {r['date']: r['params'].get(param) for r in results}
            for j, d in enumerate(all_dates):
                v = by_date.get(d)
                ws.cell(row=cur_row, column=2 + j,
                        value=v if isinstance(v, (int, float)) else None)
                _apply_data(ws.cell(row=cur_row, column=2 + j))
            cur_row += 1
        data_end = cur_row - 1

        # Standard line as extra series (ใช้ active_standards)
        std = (active_standards or {}).get(param)
        std_row = None
        if isinstance(std, dict) and std.get('max') is not None:
            ws.cell(row=cur_row, column=1,
                    value=f'มาตรฐานสูงสุด อาคาร {primary_bt} ({std["max"]})')
            _apply_data(ws.cell(row=cur_row, column=1),
                        bold=True, bg=CLR['std_bg'], align='left')
            for j in range(len(all_dates)):
                ws.cell(row=cur_row, column=2 + j, value=std['max'])
                _apply_data(ws.cell(row=cur_row, column=2 + j),
                            bold=True, bg=CLR['std_bg'])
            std_row = cur_row
            cur_row += 1

        # Line chart
        if data_end >= data_start:
            lc = LineChart()
            unit = PARAM_UNITS.get(param, '')
            unit_suffix = f' ({unit})' if unit else ''
            lc.title = f'แนวโน้ม {param}{unit_suffix}'
            # [FIX] เอาชื่อแกนออกเพื่อไม่ให้ทับ tick labels
            # ข้อมูลครบอยู่ใน title แล้ว (มีหน่วย) และ tick labels พูดเอง (วันที่)
            lc.y_axis.title = None
            lc.x_axis.title = None
            lc.height = 9
            lc.width  = 24
            lc.style  = 12

            # [FIX] เริ่ม min_row=data_start (ข้าม header "โรงพยาบาล")
            end_row = std_row if std_row else data_end
            data_ref = Reference(ws, min_col=1, min_row=data_start,
                                 max_col=1 + len(all_dates),
                                 max_row=end_row)
            lc.add_data(data_ref, titles_from_data=True, from_rows=True)
            cats = Reference(ws, min_col=2, min_row=header_r,
                             max_col=1 + len(all_dates), max_row=header_r)
            lc.set_categories(cats)

            # [FIX] บังคับให้แสดง tick labels บนแกน X และ Y
            lc.x_axis.delete  = False
            lc.y_axis.delete  = False
            lc.x_axis.majorTickMark = 'out'
            lc.y_axis.majorTickMark = 'out'

            # Legend ด้านขวา
            from openpyxl.chart.legend import Legend
            lc.legend = Legend()
            lc.legend.position = 'r'
            lc.legend.overlay = False

            # Make markers visible + thicker lines for visibility
            from openpyxl.chart.marker import Marker
            for i, s in enumerate(lc.series):
                s.smooth = False
                s.marker = Marker(symbol='circle', size=7)
                # Last series = standard line → dashed red
                if std_row and i == len(lc.series) - 1:
                    from openpyxl.chart.shapes import GraphicalProperties
                    from openpyxl.drawing.line import LineProperties
                    s.graphicalProperties = GraphicalProperties()
                    s.graphicalProperties.line = LineProperties(
                        solidFill='DC2626', w=20000, prstDash='dash')

            chart_col = get_column_letter(len(all_dates) + 5)  # +2 extra for spacing
            _set_chart_title_top(lc)
            ws.add_chart(lc, f'{chart_col}{data_start}')

        cur_row += 18   # เพิ่มระยะห่างให้พอสำหรับ chart สูง 8 units (≈16 rows)

    ws.column_dimensions['A'].width = 30
    for j in range(len(all_dates)):
        ws.column_dimensions[get_column_letter(2 + j)].width = 13

    _setup_page(ws, orientation='landscape',
                title='แนวโน้มคุณภาพน้ำเชิงเวลา')


def _build_radar_sheet(wb, hospitals_data, standards=None, hospitals_rows=None,
                       standards_by_type=None, default_building_type='ก'):
    """ชีต 'เปรียบเทียบรวม' — Radar chart แสดงภาพรวมทุกพารามิเตอร์
    ในครั้งล่าสุดของแต่ละ รพ. (เทียบกับมาตรฐานของอาคารตัวเอง)

    ใช้ค่า % เทียบกับมาตรฐาน → แต่ละโรงพยาบาลใช้มาตรฐานของอาคารตัวเอง
    เพื่อเทียบเป็นเปอร์เซ็นต์ที่ comparable กันได้
    """
    ws = wb.create_sheet(title='เปรียบเทียบรวม')

    # หา std ต่อโรงพยาบาล (จาก predominant building type)
    hosp_standards = {}
    hosp_bt = {}
    if standards_by_type and hospitals_rows:
        for hosp in hospitals_data.keys():
            rows = hospitals_rows.get(hosp, [])
            bt = _predominant_bt(rows, default=default_building_type) if rows else default_building_type
            hosp_bt[hosp] = bt
            hosp_standards[hosp] = standards_by_type.get(bt, standards or {})
    else:
        for hosp in hospitals_data.keys():
            hosp_bt[hosp] = default_building_type
            hosp_standards[hosp] = standards or {}

    # active_standards สำหรับเส้น "มาตรฐาน 100%" — ใช้อาคารหลักของกลุ่ม
    from collections import Counter
    all_bts = list(hosp_bt.values())
    if all_bts:
        primary_bt = Counter(all_bts).most_common(1)[0][0]
        active_standards = standards_by_type.get(primary_bt, standards or {}) if standards_by_type else (standards or {})
    else:
        primary_bt = default_building_type
        active_standards = standards or {}

    ws.merge_cells('A1:H1')
    c = ws['A1']
    c.value = 'ภาพรวมทุกพารามิเตอร์ (Radar Chart) — ค่าตรวจล่าสุดเทียบมาตรฐาน'
    c.font  = Font(name='Tahoma', bold=True, size=14, color=CLR['header_fg'])
    c.fill  = PatternFill('solid', fgColor=CLR['header_bg'])
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    # Note explaining normalization
    ws.merge_cells('A2:H2')
    n = ws.cell(row=2, column=1)
    n.value = ('* แสดงค่าเป็น % ของมาตรฐานของอาคารตัวเอง  '
               '(100% = ค่าเท่ามาตรฐาน, < 100% = ผ่าน, > 100% = เกินมาตรฐาน)')
    n.font = Font(name='Tahoma', italic=True, size=9, color='64748B')
    n.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 18

    # Params to show on radar (max-type only, exclude range-type pH/Cl2)
    RADAR_PARAMS = ['BOD', 'COD', 'TSS', 'TDS', 'O&G', 'TKN', 'TCB', 'FCB']

    # Header row — แสดงประเภทอาคารของแต่ละ รพ.
    hdr_row = 4
    ws.cell(row=hdr_row, column=1, value='พารามิเตอร์')
    _apply_hdr(ws.cell(row=hdr_row, column=1))
    ws.cell(row=hdr_row, column=2, value='หน่วย')
    _apply_hdr(ws.cell(row=hdr_row, column=2))
    ws.cell(row=hdr_row, column=3, value=f'มาตรฐานหลัก\n(อาคาร {primary_bt})')
    _apply_hdr(ws.cell(row=hdr_row, column=3))
    ws.cell(row=hdr_row, column=4, value='มาตรฐาน\n(100%)')
    _apply_hdr(ws.cell(row=hdr_row, column=4))
    for j, hosp in enumerate(hospitals_data.keys()):
        bt = hosp_bt.get(hosp, default_building_type)
        ws.cell(row=hdr_row, column=5 + j, value=f'{hosp}\n(อาคาร {bt})')
        _apply_hdr(ws.cell(row=hdr_row, column=5 + j))
    ws.row_dimensions[hdr_row].height = 42

    data_start = hdr_row + 1
    cur_row = data_start
    for param in RADAR_PARAMS:
        # std หลัก (เพื่อแสดงในตาราง)
        primary_std = (active_standards or {}).get(param)
        primary_max = primary_std.get('max') if isinstance(primary_std, dict) else None
        unit = PARAM_UNITS.get(param, '–')

        # ถ้าทุกโรงพยาบาลไม่กำหนดพารามิเตอร์นี้ → ข้าม
        any_regulated = False
        for hosp in hospitals_data.keys():
            hsd = hosp_standards.get(hosp, {}).get(param)
            if isinstance(hsd, dict) and hsd.get('max') is not None:
                any_regulated = True
                break
        if not any_regulated:
            continue

        # คอลัมน์ A — ชื่อพารามิเตอร์
        ws.cell(row=cur_row, column=1, value=param)
        _apply_data(ws.cell(row=cur_row, column=1), bold=True, align='center')
        # คอลัมน์ B — หน่วย
        ws.cell(row=cur_row, column=2, value=unit)
        _apply_data(ws.cell(row=cur_row, column=2), align='center')
        # คอลัมน์ C — มาตรฐานหลัก
        if primary_max is not None:
            ws.cell(row=cur_row, column=3, value=f'≤ {primary_max:,}' if primary_max >= 1000 else f'≤ {primary_max}')
        else:
            ws.cell(row=cur_row, column=3, value='ไม่กำหนด')
        _apply_data(ws.cell(row=cur_row, column=3),
                    bold=True, bg=CLR['std_bg'], align='center')
        # คอลัมน์ D — Standard 100% (สำหรับ chart series)
        ws.cell(row=cur_row, column=4, value=100)
        _apply_data(ws.cell(row=cur_row, column=4),
                    bold=True, bg=CLR['std_bg'])
        ws.row_dimensions[cur_row].height = 22

        # Latest value per hospital, normalized to % ของมาตรฐานของอาคารตัวเอง
        for j, (hosp, results) in enumerate(hospitals_data.items()):
            hsd = hosp_standards.get(hosp, {}).get(param)
            hsd_max = hsd.get('max') if isinstance(hsd, dict) else None
            latest_val = None
            for r in reversed(results):
                v = r['params'].get(param)
                if isinstance(v, (int, float)):
                    latest_val = v
                    break
            if latest_val is not None and hsd_max is not None and hsd_max > 0:
                pct_raw = latest_val / hsd_max * 100
                pct_capped = min(pct_raw, 200.0)
                cell = ws.cell(row=cur_row, column=5 + j,
                               value=round(pct_capped, 1))
                _apply_data(cell)
                if pct_raw > 100:
                    cell.font = Font(name='Tahoma', bold=True, size=10,
                                     color=CLR['fail'])
                elif pct_raw > 70:
                    cell.font = Font(name='Tahoma', bold=True, size=10,
                                     color=CLR['near'])
                else:
                    cell.font = Font(name='Tahoma', bold=True, size=10,
                                     color=CLR['pass'])
            elif latest_val is not None and hsd_max is None:
                # ไม่กำหนดสำหรับอาคารนี้ → แสดง "–"
                ws.cell(row=cur_row, column=5 + j, value='ไม่กำหนด')
                _apply_data(ws.cell(row=cur_row, column=5 + j))
            else:
                ws.cell(row=cur_row, column=5 + j, value=None)
                _apply_data(ws.cell(row=cur_row, column=5 + j))
        cur_row += 1
    data_end = cur_row - 1

    # Radar chart — ใช้ 'marker' type
    if data_end >= data_start:
        radar = RadarChart()
        radar.type = 'marker'
        radar.style = 26
        radar.title = 'เปรียบเทียบทุกพารามิเตอร์ (% ของมาตรฐานอาคารแต่ละ รพ.)'
        radar.height = 17
        radar.width  = 24

        data_ref = Reference(ws, min_col=4, min_row=hdr_row,
                             max_col=4 + len(hospitals_data),
                             max_row=data_end)
        cats_ref = Reference(ws, min_col=1, min_row=data_start,
                             max_row=data_end)
        radar.add_data(data_ref, titles_from_data=True)
        radar.set_categories(cats_ref)
        radar.legend.position = 'r'
        radar.legend.overlay = False

        from openpyxl.chart.marker import Marker
        from openpyxl.chart.shapes import GraphicalProperties
        from openpyxl.drawing.line import LineProperties
        if radar.series:
            std_series = radar.series[0]
            std_series.graphicalProperties = GraphicalProperties()
            std_series.graphicalProperties.line = LineProperties(
                solidFill='DC2626', w=22000, prstDash='dash')
            std_series.marker = Marker(symbol='none')

            hosp_colors = ['2563EB', '16A34A', '9333EA', 'EA580C', '0891B2']
            for i, s in enumerate(radar.series[1:]):
                s.marker = Marker(symbol='circle', size=10)
                s.graphicalProperties = GraphicalProperties()
                s.graphicalProperties.line = LineProperties(
                    solidFill=hosp_colors[i % len(hosp_colors)], w=22000)

        _set_chart_title_top(radar)
        ws.add_chart(radar, f'A{data_end + 4}')

    ws.column_dimensions['A'].width = 13
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 14
    for j in range(len(hospitals_data)):
        ws.column_dimensions[get_column_letter(5 + j)].width = 18

    _setup_page(ws, orientation='landscape',
                title='เปรียบเทียบทุกพารามิเตอร์ (Radar)')


def _build_chart_sheet(wb, hospitals_data, standards=None, hospitals_rows=None,
                       standards_by_type=None, default_building_type='ก'):
    """สร้างชีต 'กราฟ' รวมเทียบระหว่างโรงพยาบาลทีละพารามิเตอร์
    มาตรฐานใช้ของอาคารหลัก (predominant) ของทุกโรงพยาบาลรวมกัน
    """
    # หา active_standards (predominant ของทั้งหมด)
    if standards_by_type and hospitals_rows:
        from collections import Counter
        all_bts = []
        for rows in hospitals_rows.values():
            all_bts.extend(_building_types_in(rows, default=default_building_type))
        if all_bts:
            primary_bt = Counter(all_bts).most_common(1)[0][0]
            active_standards = standards_by_type.get(primary_bt, standards or {})
        else:
            primary_bt = default_building_type
            active_standards = standards or {}
    else:
        primary_bt = default_building_type
        active_standards = standards or {}

    ws = wb.create_sheet(title='กราฟ')

    # Title
    ws.merge_cells('A1:H1')
    c = ws['A1']
    c.value = 'กราฟเปรียบเทียบค่าพารามิเตอร์ในแต่ละวัน'
    c.font  = Font(name='Tahoma', bold=True, size=14, color=CLR['header_fg'])
    c.fill  = PatternFill('solid', fgColor=CLR['header_bg'])
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 26

    # สำหรับแต่ละพารามิเตอร์ ให้วาดตาราง + chart
    chart_params = ['pH', 'BOD', 'COD', 'TSS', 'TDS', 'O&G',
                    'TKN', 'Sulfide', 'NH4', 'TCB', 'FCB', 'Cl2', 'DO']

    # หา dates union ของทุกโรงพยาบาล
    all_dates = []
    for hosp, results in hospitals_data.items():
        for r in results:
            if r['date'] != '–' and r['date'] not in all_dates:
                all_dates.append(r['date'])
    all_dates.sort(key=lambda x: (x.split('/')[::-1] if '/' in x else x))

    cur_row = 3
    for param in chart_params:
        # Section title
        ws.merge_cells(start_row=cur_row, start_column=1,
                       end_row=cur_row,   end_column=len(all_dates) + 1)
        t = ws.cell(row=cur_row, column=1)
        t.value = f'ค่า {param} เทียบมาตรฐานน้ำทิ้ง'
        t.font  = Font(name='Tahoma', bold=True, size=12, color='FFFFFF')
        t.fill  = PatternFill('solid', fgColor=CLR['subheader'])
        t.alignment = Alignment(horizontal='left', vertical='center',
                                indent=1)
        ws.row_dimensions[cur_row].height = 22
        cur_row += 1

        # Header row (dates)
        ws.cell(row=cur_row, column=1).value = 'โรงพยาบาล'
        _apply_hdr(ws.cell(row=cur_row, column=1))
        for j, d in enumerate(all_dates):
            ws.cell(row=cur_row, column=2 + j).value = d
            _apply_hdr(ws.cell(row=cur_row, column=2 + j))
        header_r = cur_row
        cur_row += 1

        # Data row per hospital
        data_start = cur_row
        for hosp, results in hospitals_data.items():
            ws.cell(row=cur_row, column=1).value = hosp
            _apply_data(ws.cell(row=cur_row, column=1), bold=True, align='left')
            # map date → value
            by_date = {}
            for r in results:
                v = r['params'].get(param)
                by_date[r['date']] = v if isinstance(v, (int, float)) else None
            for j, d in enumerate(all_dates):
                v = by_date.get(d)
                ws.cell(row=cur_row, column=2 + j).value = v if v is not None else None
                _apply_data(ws.cell(row=cur_row, column=2 + j))
            cur_row += 1
        data_end = cur_row - 1

        # Standard rows (reference lines) — ใช้ active_standards
        std = (active_standards or {}).get(param)
        if not isinstance(std, dict):
            std = {}
        std_rows = []
        if std.get('min') is not None:
            ws.cell(row=cur_row, column=1).value = f'มาตรฐาน อาคาร {primary_bt} ต่ำสุดไม่ต่ำกว่า {std["min"]}'
            _apply_data(ws.cell(row=cur_row, column=1),
                        bold=True, bg=CLR['std_bg'], align='left')
            for j in range(len(all_dates)):
                ws.cell(row=cur_row, column=2 + j).value = std['min']
                _apply_data(ws.cell(row=cur_row, column=2 + j),
                            bold=True, bg=CLR['std_bg'])
            std_rows.append(cur_row); cur_row += 1
        if std.get('max') is not None:
            ws.cell(row=cur_row, column=1).value = f'มาตรฐาน อาคาร {primary_bt} สูงสุดไม่เกิน {std["max"]}'
            _apply_data(ws.cell(row=cur_row, column=1),
                        bold=True, bg=CLR['std_bg'], align='left')
            for j in range(len(all_dates)):
                ws.cell(row=cur_row, column=2 + j).value = std['max']
                _apply_data(ws.cell(row=cur_row, column=2 + j),
                            bold=True, bg=CLR['std_bg'])
            std_rows.append(cur_row); cur_row += 1

        # Add chart — BarChart (hospital values) + LineChart overlaid (standard)
        if data_end >= data_start and len(all_dates) > 0:
            from openpyxl.chart.legend import Legend
            from openpyxl.chart.marker import Marker
            from openpyxl.chart.shapes import GraphicalProperties
            from openpyxl.drawing.line import LineProperties
            from openpyxl.chart.text import RichText
            from openpyxl.drawing.text import (
                Paragraph, ParagraphProperties, CharacterProperties,
                RichTextProperties
            )

            bar = BarChart()
            bar.type = 'col'
            bar.style = 11
            unit = PARAM_UNITS.get(param, '')
            unit_suffix = f' ({unit})' if unit else ''
            bar.title = f'ค่า {param}'
            # [FIX] เอาชื่อแกนออก ป้องกันทับ tick labels
            bar.y_axis.title = None
            bar.x_axis.title = None
            bar.height = 9
            bar.width  = 22

            # [FIX] เริ่ม min_row=data_start (ข้าม header "โรงพยาบาล")
            #       เพื่อไม่ให้คอลัมน์แรกของ header กลายเป็นชื่อ series ผิด ๆ
            data_ref = Reference(ws, min_col=1, min_row=data_start,
                                 max_col=1 + len(all_dates), max_row=data_end)
            bar.add_data(data_ref, titles_from_data=True, from_rows=True)
            cats = Reference(ws, min_col=2, min_row=header_r,
                             max_col=1 + len(all_dates), max_row=header_r)
            bar.set_categories(cats)

            # [FIX] บังคับให้แกน X และ Y แสดง tick labels (วันที่และตัวเลข)
            bar.x_axis.delete  = False    # แสดงแกน X
            bar.y_axis.delete  = False    # แสดงแกน Y
            bar.x_axis.majorTickMark = 'out'
            bar.y_axis.majorTickMark = 'out'

            # Legend ด้านขวา
            bar.legend = Legend()
            bar.legend.position = 'r'
            bar.legend.overlay  = False

            # Standard as overlaid LineChart with dashed red style
            if std_rows:
                line = LineChart()
                line_data = Reference(ws, min_col=1, min_row=std_rows[0],
                                      max_col=1 + len(all_dates),
                                      max_row=std_rows[-1])
                line.add_data(line_data, titles_from_data=True, from_rows=True)
                # ทำให้เส้นมาตรฐานเป็นเส้นประแดง ไม่มี marker ให้รบกวน
                for s in line.series:
                    s.smooth = False
                    s.marker = Marker(symbol='none')
                    s.graphicalProperties = GraphicalProperties()
                    s.graphicalProperties.line = LineProperties(
                        solidFill='DC2626', w=20000, prstDash='dash')
                bar += line    # overlay

            # เพิ่ม chart spacing - เพิ่มระยะห่างจากตาราง
            chart_col = get_column_letter(len(all_dates) + 4)
            _set_chart_title_top(bar)
            ws.add_chart(bar, f'{chart_col}{data_start}')

        # เพิ่มระยะห่างให้พอสำหรับ chart (สูง 9 units ≈ 18 rows)
        cur_row += 19

    # column widths
    ws.column_dimensions['A'].width = 32
    for j in range(len(all_dates)):
        ws.column_dimensions[get_column_letter(2 + j)].width = 13

    _setup_page(ws, orientation='landscape',
                title='กราฟเปรียบเทียบรายพารามิเตอร์')


def build_hospital_xlsx_report(hospitals_rows,
                               fuzzy_system=None,
                               build_parameters=None,
                               can_fuzzy_eval=None,
                               score_to_overall_status=None,
                               standards=None,
                               title_suffix='',
                               get_fuzzy_system=None,
                               default_building_type='ก',
                               standards_by_type=None):
    """สร้างไฟล์ Excel รายงานรวม

    hospitals_rows:  dict {  'ชื่อโรงพยาบาล': [WaterQualityData, ...],  ...  }
    get_fuzzy_system: callable(building_type) -> fuzzy_system (เพื่อรองรับ ก/ข/ค/ง)
    default_building_type: 'ก' / 'ข' / 'ค' / 'ง' (ใช้ถ้า row ไม่มี building_type)
    standards_by_type: dict {bt: standards_dict} — มาตรฐานต่อประเภทอาคาร

    คืน bytes ของไฟล์ .xlsx
    """
    wb = Workbook()
    # ลบ default sheet
    wb.remove(wb.active)

    # ── Summary sheet (first) ──────────────────────────────────
    ws_sum = wb.create_sheet(title='สรุปรวม')
    ws_sum.merge_cells('A1:F1')
    c = ws_sum['A1']
    c.value = 'รายงานคุณภาพน้ำทิ้ง — สรุปรวมทุกโรงพยาบาล' + (f'  ({title_suffix})' if title_suffix else '')
    c.font  = Font(name='Tahoma', bold=True, size=14, color=CLR['header_fg'])
    c.fill  = PatternFill('solid', fgColor=CLR['header_bg'])
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws_sum.row_dimensions[1].height = 28

    # Count totals for metadata
    total_rows = sum(len(r) for r in hospitals_rows.values())
    all_dates_list = []
    for rows in hospitals_rows.values():
        for w in rows:
            d = getattr(w, 'sample_date', None)
            if d: all_dates_list.append(d)
    date_range = '–'
    if all_dates_list:
        dmin = min(all_dates_list).strftime('%d/%m/%Y')
        dmax = max(all_dates_list).strftime('%d/%m/%Y')
        date_range = f'{dmin} ถึง {dmax}'

    # Metadata block (rows 2-4)
    next_row = _write_metadata_block(
        ws_sum, start_row=2,
        location=f'{len(hospitals_rows)} โรงพยาบาล',
        row_count=total_rows, date_range=date_range,
    )

    # Summary table headers (no pass rate)
    ws_sum.row_dimensions[next_row].height = 22
    for i, h in enumerate(['โรงพยาบาล', 'จำนวนครั้ง', 'ผ่าน',
                            'เฝ้าระวัง', 'เกินมาตรฐาน', 'ไม่มีข้อมูล']):
        cell = ws_sum.cell(row=next_row, column=1 + i, value=h)
        _apply_hdr(cell)
    header_row = next_row
    next_row += 1

    hospitals_data = {}
    compliance_data = {}    # สำหรับกราฟ compliance rate
    srow = next_row
    data_start_row = srow
    for loc, rows in hospitals_rows.items():
        chart_data, stats = _build_hospital_sheet(
            wb, sheet_name=loc, location=loc, rows_raw=rows,
            fuzzy_system=fuzzy_system,
            build_parameters=build_parameters,
            can_fuzzy_eval=can_fuzzy_eval,
            score_to_overall_status=score_to_overall_status,
            standards=standards,
            get_fuzzy_system=get_fuzzy_system,
            default_building_type=default_building_type,
            standards_by_type=standards_by_type,
        )
        hospitals_data[loc] = chart_data
        compliance_data[loc] = stats

        vals = [loc, stats['total'], stats['pass'], stats['near'],
                stats['fail'], stats['nodata']]
        for i, v in enumerate(vals):
            cell = ws_sum.cell(row=srow, column=1 + i, value=v)
            _apply_data(cell, align='left' if i == 0 else 'center',
                        bold=(i == 0))
        srow += 1
    data_end_row = srow - 1

    # Column widths (no pass rate col)
    for i, w in enumerate([28, 13, 11, 12, 16, 14]):
        ws_sum.column_dimensions[get_column_letter(1 + i)].width = w

    # ── Compliance Rate Bar Chart (on summary sheet) ──────────
    if compliance_data:
        comp_chart = BarChart()
        comp_chart.type = 'col'
        comp_chart.style = 10
        comp_chart.grouping = 'stacked'
        comp_chart.overlap = 100
        comp_chart.title = 'สัดส่วนผลการประเมินต่อโรงพยาบาล (จำนวนครั้ง)'
        # [FIX] เอาชื่อแกนออก ป้องกันทับ tick labels (ชื่อ รพ. ยาว)
        comp_chart.y_axis.title = None
        comp_chart.x_axis.title = None
        comp_chart.height = 9
        comp_chart.width  = 18

        # Use pass/near/fail columns (cols 3,4,5) as stacked series
        data_ref = Reference(ws_sum, min_col=3, min_row=header_row,
                             max_col=5, max_row=data_end_row)
        cats_ref = Reference(ws_sum, min_col=1, min_row=data_start_row,
                             max_row=data_end_row)
        comp_chart.add_data(data_ref, titles_from_data=True)
        comp_chart.set_categories(cats_ref)
        # บังคับให้แสดง tick labels (จำนวน + ชื่อ รพ.)
        comp_chart.x_axis.delete  = False
        comp_chart.y_axis.delete  = False
        comp_chart.x_axis.majorTickMark = 'out'
        comp_chart.y_axis.majorTickMark = 'out'
        # วาง legend ด้านขวา ไม่ใช่ด้านล่าง เพื่อไม่ให้ทับกับ x-axis title
        from openpyxl.chart.legend import Legend
        comp_chart.legend = Legend()
        comp_chart.legend.position = 'r'
        comp_chart.legend.overlay = False

        # Color series: pass=green, near=amber, fail=red
        try:
            from openpyxl.chart.shapes import GraphicalProperties
            from openpyxl.drawing.fill import PatternFillProperties, ColorChoice
            from openpyxl.drawing.colors import ColorChoice as CC
            colors = [CLR['pass'], CLR['near'], CLR['fail']]
            for i, s in enumerate(comp_chart.series):
                s.graphicalProperties = GraphicalProperties(solidFill=colors[i])
        except Exception:
            pass

        _set_chart_title_top(comp_chart)
        ws_sum.add_chart(comp_chart, f'A{data_end_row + 5}')   # วางใต้ตาราง เว้น 4 แถว

    # ── Page setup for summary ──────────────────────────────
    _setup_page(ws_sum, orientation='landscape',
                title='รายงานคุณภาพน้ำทิ้ง — สรุปรวม')

    # ── Statistics sheet ────────────────────────────────────
    _build_statistics_sheet(wb, hospitals_rows, standards=standards,
                            standards_by_type=standards_by_type,
                            default_building_type=default_building_type)

    # ── Trend sheet (time-series for key params) ──────────────
    if hospitals_data:
        _build_trend_sheet(wb, hospitals_data, standards=standards,
                           hospitals_rows=hospitals_rows,
                           standards_by_type=standards_by_type,
                           default_building_type=default_building_type)

    # ── Radar/comparison sheet ─────────────────────────────
    if hospitals_data:
        _build_radar_sheet(wb, hospitals_data, standards=standards,
                           hospitals_rows=hospitals_rows,
                           standards_by_type=standards_by_type,
                           default_building_type=default_building_type)

    # ── Chart sheet — per-param comparison ───────────────
    if hospitals_data:
        _build_chart_sheet(wb, hospitals_data, standards=standards,
                           hospitals_rows=hospitals_rows,
                           standards_by_type=standards_by_type,
                           default_building_type=default_building_type)

    # write to bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    # ── Post-process XML: fix radar chart category labels for Excel ──────
    # openpyxl bug: RadarChart.set_categories() ใช้ <numRef> เสมอ
    # แต่ค่าเป็น string ทำให้ Excel ไม่แสดง label
    # นอกจากนี้ catAx ขาด <tickLblPos> ทำให้ Excel ซ่อน labels
    fixed_data = _fix_radar_chart_xml(buf.read())
    return fixed_data


def _fix_radar_chart_xml(xlsx_bytes):
    """Fix Excel-specific radar chart issues by editing chart XML directly:
    1. Convert <numRef> → <strRef> in <cat> tags (categories are strings, not numbers)
    2. Replace entire <catAx> with Excel-compliant version that has all required
       properties (delete, auto, lblAlgn, noMultiLvlLbl) — without these, Excel
       silently hides category labels around the radar chart
    """
    import zipfile, io as _io, re

    # Excel-compliant catAx — ครบทุก property ที่ Excel ต้องการ
    # ที่สำคัญ: <delete val="0"/> บอกว่า axis "ไม่ได้ถูกซ่อน"
    EXCEL_COMPLIANT_CATAX = (
        '<catAx>'
        '<axId val="10"/>'
        '<scaling><orientation val="minMax"/></scaling>'
        '<delete val="0"/>'
        '<axPos val="b"/>'
        '<majorTickMark val="out"/>'
        '<minorTickMark val="none"/>'
        '<tickLblPos val="nextTo"/>'
        '<crossAx val="100"/>'
        '<crosses val="autoZero"/>'
        '<auto val="1"/>'
        '<lblAlgn val="ctr"/>'
        '<lblOffset val="100"/>'
        '<noMultiLvlLbl val="0"/>'
        '</catAx>'
    )

    # Excel-compliant valAx เช่นกัน
    EXCEL_COMPLIANT_VALAX = (
        '<valAx>'
        '<axId val="100"/>'
        '<scaling><orientation val="minMax"/></scaling>'
        '<delete val="0"/>'
        '<axPos val="l"/>'
        '<majorGridlines/>'
        '<numFmt formatCode="General" sourceLinked="1"/>'
        '<majorTickMark val="out"/>'
        '<minorTickMark val="none"/>'
        '<tickLblPos val="nextTo"/>'
        '<crossAx val="10"/>'
        '<crosses val="autoZero"/>'
        '<crossBetween val="between"/>'
        '</valAx>'
    )

    src = _io.BytesIO(xlsx_bytes)
    dst = _io.BytesIO()

    with zipfile.ZipFile(src, 'r') as zin:
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.namelist():
                content = zin.read(item)
                if (item.startswith('xl/charts/chart') and item.endswith('.xml')):
                    text = content.decode('utf-8')
                    if '<radarChart>' in text:
                        # 1. แก้ <cat><numRef> → <cat><strRef>
                        text = re.sub(
                            r'<cat>\s*<numRef>',
                            '<cat><strRef>',
                            text
                        )
                        text = re.sub(
                            r'</numRef>(\s*)</cat>',
                            r'</strRef>\1</cat>',
                            text
                        )
                        # 2. แทน catAx ทั้งบล็อค ด้วยเวอร์ชันที่ Excel เข้าใจ
                        text = re.sub(
                            r'<catAx>.*?</catAx>',
                            EXCEL_COMPLIANT_CATAX,
                            text,
                            flags=re.DOTALL
                        )
                        # 3. แทน valAx ด้วยเวอร์ชันที่ Excel เข้าใจ
                        text = re.sub(
                            r'<valAx>.*?</valAx>',
                            EXCEL_COMPLIANT_VALAX,
                            text,
                            flags=re.DOTALL
                        )
                        content = text.encode('utf-8')
                zout.writestr(item, content)

    dst.seek(0)
    return dst.read()


def build_single_result_xlsx(water_data, evaluation=None,
                             fuzzy_system=None,
                             build_parameters=None,
                             can_fuzzy_eval=None,
                             score_to_overall_status=None,
                             standards=None,
                             username=None,
                             building_type=None):
    """สร้างไฟล์ Excel สำหรับ 1 ผลการประเมิน"""
    wb = Workbook()
    ws = wb.active
    ws.title = 'ผลการประเมิน'

    loc  = getattr(water_data, 'sample_location', '') or '–'
    pond = getattr(water_data, 'pond_name', '') or '–'
    date = getattr(water_data, 'sample_date', None)
    stype = getattr(water_data, 'sample_type', '') or '–'
    bt = building_type or getattr(water_data, 'building_type', None) or 'ก'

    # Title
    ws.merge_cells('A1:D1')
    c = ws['A1']
    c.value = f'รายงานผลการประเมินคุณภาพน้ำ (รายครั้ง) — {loc}'
    c.font  = Font(name='Tahoma', bold=True, size=13, color=CLR['header_fg'])
    c.fill  = PatternFill('solid', fgColor=CLR['header_bg'])
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    # Info table
    info = [
        ('สถานที่',           loc),
        ('บ่อ / ระบบบำบัด',   pond),
        ('ประเภทอาคาร',       f'อาคารประเภท {bt} (ตาม ประกาศ ทส. พ.ศ. 2567)'),
        ('วันที่เก็บตัวอย่าง', _fmt_date(date)),
        ('ประเภทตัวอย่าง',    stype),
        ('บันทึกโดย',          username or '–'),
    ]
    for i, (k, v) in enumerate(info):
        ws.cell(row=3 + i, column=1, value=k)
        ws.cell(row=3 + i, column=2, value=v)
        _apply_data(ws.cell(row=3 + i, column=1), bold=True,
                    bg=CLR['note_bg'], align='left')
        _apply_data(ws.cell(row=3 + i, column=2), align='left')

    # Evaluation
    params = None
    if build_parameters:
        params = build_parameters(water_data)
    score = None
    status_en = 'No Data'
    msg = ''
    pr = {}
    if params and can_fuzzy_eval and can_fuzzy_eval(params) and fuzzy_system:
        ev = fuzzy_system.evaluate_overall(params)
        score = ev.get('overall_score')
        msg   = ev.get('overall_message', '')
        pr    = ev.get('parameter_results', {}) or {}
        if score is not None and score_to_overall_status:
            status_en = score_to_overall_status(score)

    # KPI row
    r = 3 + len(info) + 1
    ws.cell(row=r, column=1, value='Fuzzy Score')
    ws.cell(row=r, column=2,
            value=f'{round(score,1)} / 100' if score is not None else '–')
    ws.cell(row=r, column=3, value='สถานะ')
    ws.cell(row=r, column=4, value=_status_th(status_en))
    for col in (1, 3):
        _apply_data(ws.cell(row=r, column=col), bold=True,
                    bg=CLR['note_bg'])
    for col in (2, 4):
        _apply_data(ws.cell(row=r, column=col), bold=True,
                    color=_status_color(status_en))

    # Parameter table
    r += 2
    headers = ['พารามิเตอร์', 'ค่าที่วัด', 'มาตรฐาน', 'สถานะ']
    for i, h in enumerate(headers):
        _apply_hdr(ws.cell(row=r, column=1 + i, value=h))
    r += 1
    label_map = {
        'pH':'pH', 'BOD':'BOD (mg/L)', 'COD':'COD (mg/L)',
        'TSS':'TSS (mg/L)', 'TDS':'TDS (mg/L)',
        'O&G':'O&G (mg/L)', 'TKN':'TKN (mg/L)',
        'Sulfide':'Sulfide (mg/L)', 'TCB':'TCB (MPN/100mL)',
        'FCB':'FCB (MPN/100mL)', 'Cl2':'Cl2 (mg/L)',
    }
    for key in ['pH','BOD','COD','TSS','TDS','O&G','TKN','Sulfide','TCB','FCB','Cl2']:
        v = params.get(key) if params else None
        stat = (pr.get(key, {}) or {}).get('status', '–') if pr else '–'
        stdv = (standards or {}).get(key, {})
        # ตรวจว่าเป็น "ไม่กำหนด" หรือไม่ (regulated=False หรือไม่มี max/min ทั้งคู่)
        is_unreg = (stdv is None or stdv.get('regulated') is False
                    or (stdv.get('min') is None and stdv.get('max') is None))
        if is_unreg:
            std_txt = 'ไม่กำหนด'
            stat = 'ไม่กำหนด'
        elif stdv.get('min') is not None and stdv.get('max') is not None:
            std_txt = f'{stdv["min"]}–{stdv["max"]}'
        elif stdv.get('max') is not None:
            std_txt = f'≤ {stdv["max"]}'
        else:
            std_txt = '–'
        ws.cell(row=r, column=1, value=label_map.get(key, key))
        ws.cell(row=r, column=2, value=_fmt_num(v))
        ws.cell(row=r, column=3, value=std_txt)
        ws.cell(row=r, column=4, value=_status_th(stat) if stat != 'ไม่กำหนด' else 'ไม่กำหนด')
        _apply_data(ws.cell(row=r, column=1), bold=True, align='left')
        _apply_data(ws.cell(row=r, column=2))
        _apply_data(ws.cell(row=r, column=3))
        sc = ws.cell(row=r, column=4)
        if is_unreg:
            _apply_data(sc, bold=False, color='94A3B8')
        else:
            _apply_data(sc, bold=True, color=_status_color(stat))
        r += 1

    # Message
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    ws.cell(row=r, column=1, value=f'ข้อความ: {msg}' if msg else 'ข้อความ: –')
    _apply_data(ws.cell(row=r, column=1), align='left', bg=CLR['note_bg'])

    # Widths
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 22
    ws.column_dimensions['C'].width = 16
    ws.column_dimensions['D'].width = 20

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()