# ระบบประเมินและติดตามคุณภาพน้ำทิ้ง (Water Quality Assessment System)

เว็บแอปพลิเคชันสำหรับประเมินคุณภาพน้ำทิ้งโดยใช้เทคนิค Fuzzy Logic

> **🆕 v2.0 — รองรับมาตรฐาน พ.ศ. 2567 + WQI Score Bands**
>
> - **ประเภทอาคาร 4 ประเภท (ก/ข/ค/ง)** — แต่ละประเภทใช้ค่ามาตรฐาน (S) ต่างกัน
>   - **ก** (รพ. ≥ 30 เตียง) — เข้มงวดที่สุด
>   - **ข** (รพ. 10–29 เตียง)
>   - **ค** (รพ. < 10 เตียง / สถานพยาบาลขนาดเล็ก) — TCB/FCB/Cl2 ไม่กำหนด
>   - **ง** (ขนาดเล็กสุด) — TKN/Sulfide/TDS/TCB/FCB/Cl2 ไม่กำหนด
> - **WQI Score Bands ใหม่** (สอดคล้อง NSF-WQI / RID Thailand):
>   - 80–100 = Excellent ✅✅
>   - 60–79  = Good ✅ (Pass)
>   - 40–59  = Fair (Near Limit / เฝ้าระวัง)
>   - 20–39  = Poor (Fail)
>   - 0–19   = Very Poor
> - Auto migration เพิ่ม column `building_type` ลง SQLite อัตโนมัติตอน startup
> - อัปโหลด Excel รองรับคอลัมน์ `building_type` หรือ `ประเภทอาคาร` ในไฟล์ (ถ้าไม่มี ใช้ default จาก dropdown)
> - **อ้างอิง:** ประกาศกระทรวงทรัพยากรธรรมชาติและสิ่งแวดล้อม เรื่อง กำหนดมาตรฐานควบคุมการระบายน้ำทิ้งจากอาคารบางประเภทและบางขนาด พ.ศ. 2567 (ราชกิจจานุเบกษา 27 ส.ค. 2567)

## 📋 คุณสมบัติหลัก

- ✅ ประเมินคุณภาพน้ำจาก 11 พารามิเตอร์
- ✅ ใช้เทคนิค Fuzzy Logic — คะแนน 0–100 ตาม WQI bands (5 ระดับ)
- ✅ รองรับมาตรฐานน้ำทิ้งอาคาร 4 ประเภท (ก/ข/ค/ง) ตาม ประกาศ ทส. 2567
- ✅ รับข้อมูลผ่านการกรอกฟอร์มหรืออัปโหลด Excel
- ✅ แสดงผลในรูปแบบ Dashboard พร้อมกราฟแนวโน้ม
- ✅ ระบบจัดการผู้ใช้ (Admin และ Guest)
- ✅ บันทึกประวัติการประเมินทั้งหมด

## 🛠️ เทคโนโลยีที่ใช้

- **Backend:** Python, Flask
- **Frontend:** HTML, CSS, JavaScript, Bootstrap 5, Chart.js
- **Database:** SQLite (สำหรับพัฒนา) / MySQL (สำหรับ Production)
- **Fuzzy Logic:** scikit-fuzzy
- **Excel Processing:** Pandas, openpyxl

## 📦 การติดตั้ง

### 1. ติดตั้ง Python
ตรวจสอบว่ามี Python 3.8+ แล้วโดยพิมพ์:
```bash
python --version
```

### 2. ดาวน์โหลดโปรเจค
วางโฟลเดอร์ `water-quality-assessment` ไว้ที่ไดรฟ์ของคุณ เช่น:
```
C:\Users\YourName\water-quality-assessment
```

### 3. เปิด Command Prompt และเข้าไปในโฟลเดอร์โปรเจค
```bash
cd C:\Users\YourName\water-quality-assessment
```

### 4. สร้าง Virtual Environment (แนะนำ)
```bash
python -m venv venv
```

เปิดใช้งาน Virtual Environment:
- **Windows:**
  ```bash
  venv\Scripts\activate
  ```
- **Mac/Linux:**
  ```bash
  source venv/bin/activate
  ```

### 5. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

### 6. เริ่มต้นฐานข้อมูล
```bash
python init_db.py
```

คำสั่งนี้จะ:
- สร้างฐานข้อมูล SQLite
- สร้างตารางทั้งหมด
- สร้างบัญชี Admin เริ่มต้น
- สร้างข้อมูลตัวอย่าง

## 🚀 การรันโปรแกรม

```bash
python app.py
```

เปิดเว็บเบราว์เซอร์แล้วไปที่:
```
http://localhost:5000
```

## 🔐 บัญชีเริ่มต้น

- **ชื่อผู้ใช้:** admin
- **รหัสผ่าน:** admin123

## 📊 พารามิเตอร์ที่ประเมิน

| พารามิเตอร์ | ค่ามาตรฐาน | หน่วย |
|------------|-----------|------|
| pH | 5.5 - 9.0 | - |
| BOD | ≤ 20 | mg/L |
| COD | ≤ 120 | mg/L |
| TSS | ≤ 30 | mg/L |
| TDS | ≤ 1000 | mg/L |
| O&G | ≤ 20 | mg/L |
| TKN | ≤ 35 | mg/L |
| Sulfide | ≤ 0 | mg/L |
| TCB | ≤ 5000 | MPN/100mL |
| FCB | ≤ 1000 | MPN/100mL |
| Cl₂ | ≤ 1 | mg/L |

**พารามิเตอร์เสริม (ไม่นำมาประเมิน):**
- NH₄⁺ (Ammonium)
- DO (Dissolved Oxygen)

## 📁 โครงสร้างโปรเจค

```
water-quality-assessment/
├── app.py                 # ไฟล์หลัก Flask application
├── config.py              # ไฟล์ตั้งค่า
├── models.py              # Database models
├── fuzzy_logic.py         # Fuzzy Logic engine
├── init_db.py             # Script สำหรับสร้าง database
├── requirements.txt       # รายการ dependencies
├── README.md              # คู่มือการใช้งาน
├── templates/             # HTML templates
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── add_data.html
│   ├── upload_data.html
│   ├── result.html
│   ├── history.html
│   ├── 404.html
│   └── 500.html
├── static/               # Static files
│   ├── css/
│   │   └── style.css
│   ├── js/
│   └── uploads/
└── database/            # Database files (จะถูกสร้างอัตโนมัติ)
```

## 📝 การใช้งาน

### 1. เข้าสู่ระบบ
- ใช้บัญชี admin / admin123

### 2. กรอกข้อมูล
- **วิธีที่ 1:** คลิก "กรอกข้อมูล" แล้วกรอกค่าพารามิเตอร์ทีละตัว
- **วิธีที่ 2:** คลิก "อัปโหลด Excel" แล้วอัปโหลดไฟล์ Excel

### 3. ดูผลการประเมิน
- ระบบจะประเมินอัตโนมัติและแสดงผลทันที
- สามารถดูรายละเอียดแต่ละพารามิเตอร์ได้

### 4. ดู Dashboard
- แสดงกราฟแนวโน้ม
- สถิติโดยรวม
- ข้อมูลล่าสุด

### 5. ดูประวัติ
- ดูข้อมูลและผลการประเมินย้อนหลังทั้งหมด

## 📤 รูปแบบไฟล์ Excel

ไฟล์ Excel ต้องมีคอลัมน์ดังนี้:

**คอลัมน์บังคับ:**
- sample_date (วันที่ เช่น 2025-01-15 10:00:00)
- pH, BOD, COD, TSS, TDS, O&G, TKN, Sulfide, TCB, FCB, Cl2

**คอลัมน์ไม่บังคับ:**
- sample_location
- sample_type
- NH4
- DO

## 🔧 การปรับแต่ง

### เปลี่ยนฐานข้อมูลเป็น MySQL
แก้ไขไฟล์ `config.py`:
```python
SQLALCHEMY_DATABASE_URI = 'mysql://username:password@localhost/water_quality_db'
```

### เปลี่ยน Secret Key
แก้ไขไฟล์ `config.py`:
```python
SECRET_KEY = 'your-secret-key-here'
```

## ❓ การแก้ปัญหา

### ปัญหา: Import Error
**วิธีแก้:** ติดตั้ง dependencies ใหม่
```bash
pip install -r requirements.txt --upgrade
```

### ปัญหา: Database Error
**วิธีแก้:** ลบไฟล์ database และสร้างใหม่
```bash
python init_db.py
```

### ปัญหา: Port 5000 ถูกใช้งานแล้ว
**วิธีแก้:** เปลี่ยน port ในไฟล์ `app.py` บรรทัดสุดท้าย:
```python
app.run(debug=True, host='0.0.0.0', port=5001)
```

## 📧 ติดต่อ

หากมีปัญหาหรือข้อสงสัย กรุณาติดต่อผู้พัฒนา

## 📄 License

โปรเจคนี้สร้างขึ้นเพื่อการศึกษา

---

**พัฒนาโดย:** [ชื่อของคุณ]  
**ปี:** 2025  
**เวอร์ชัน:** 1.0.0
