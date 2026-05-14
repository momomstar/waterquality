# ⚡ Quick Start Guide - เริ่มใช้งานภายใน 5 นาที

## 📋 เตรียมพร้อม
- ✅ Python 3.8+ (คุณมี Python 3.13.0)
- ✅ แตกไฟล์โปรเจค water-quality-assessment

---

## 🚀 3 ขั้นตอนเริ่มใช้งาน

### ขั้นที่ 1: เปิด Command Prompt
```bash
cd path\to\water-quality-assessment
```

### ขั้นที่ 2: ติดตั้งและเริ่มต้น
```bash
pip install -r requirements.txt
python init_db.py
```

### ขั้นที่ 3: รันโปรแกรม
```bash
python app.py
```

**เปิดเว็บ:** http://localhost:5000  
**Login:** admin / admin123

---

## 🎯 ทดสอบระบบ

### วิธีที่ 1: กรอกข้อมูลด้วยมือ
1. คลิก "กรอกข้อมูล"
2. กรอกค่าพารามิเตอร์:
   - pH: 7.5
   - BOD: 15, COD: 100
   - TSS: 25, TDS: 800
   - O&G: 18, TKN: 30
   - Sulfide: 0
   - TCB: 4000, FCB: 800
   - Cl₂: 0.8
3. บันทึก → ดูผล

### วิธีที่ 2: อัปโหลด Excel
1. คลิก "อัปโหลด Excel"
2. เลือกไฟล์ **sample_data.xlsx**
3. อัปโหลด → ดูผล

---

## 📊 ดู Dashboard
- สถิติโดยรวม
- กราฟแนวโน้ม
- ข้อมูลล่าสุด

---

## ❓ แก้ปัญหาด่วน

**Port 5000 ถูกใช้?**
```python
# แก้ไขในไฟล์ app.py บรรทัดสุดท้าย
app.run(debug=True, host='0.0.0.0', port=5001)
```

**ติดตั้ง Library ไม่ได้?**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Database Error?**
```bash
# ลบไฟล์ database แล้วสร้างใหม่
python init_db.py
```

---

## 🎓 ต้องการรายละเอียดเพิ่มเติม?
อ่าน **INSTALL_GUIDE.md** สำหรับคำแนะนำแบบละเอียด

---

**พร้อมใช้งาน!** 🎉
