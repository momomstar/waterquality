# 🚀 คำสั่งที่ใช้บ่อย (Cheat Sheet)

## 📦 การติดตั้ง

### ครั้งแรก

```bash
# 1. เข้าโฟลเดอร์โปรเจค
cd path/to/water-quality-assessment

# 2. สร้าง Virtual Environment (แนะนำ)
python -m venv venv

# 3. เปิดใช้งาน Virtual Environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. ติดตั้ง Dependencies
pip install -r requirements.txt

# 5. เริ่มต้นฐานข้อมูล
python init_db.py
```

---

## 🎮 การใช้งานปกติ

### รันโปรแกรม

```bash
python app.py
```

### เปิดเว็บ

```
http://localhost:5000
```

### Login

```
Username: admin
Password: admin123
```

### หยุดโปรแกรม

```
กด Ctrl + C
```

---

## 🔧 คำสั่งอื่นๆ

### ตรวจสอบ Python Version

```bash
python --version
```

### ตรวจสอบ Packages ที่ติดตั้ง

```bash
pip list
```

### อัพเดท pip

```bash
python -m pip install --upgrade pip
```

### ติดตั้ง Package เดียว

```bash
pip install flask
```

### ลบ Package

```bash
pip uninstall flask
```

### Freeze Dependencies

```bash
pip freeze > requirements.txt
```

---

## 💾 Database

### สร้าง Database ใหม่

```bash
python init_db.py
```

### รีเซ็ต Database (ลบและสร้างใหม่)

```bash
# ลบไฟล์ database
# Windows:
del water_quality.db
# Mac/Linux:
rm water_quality.db

# สร้างใหม่
python init_db.py
```

### Backup Database

```bash
# Windows:
copy water_quality.db water_quality_backup.db
# Mac/Linux:
cp water_quality.db water_quality_backup.db
```

---

## 🐛 Debug

### รัน Debug Mode

```python
# ใน app.py บรรทัดสุดท้าย:
app.run(debug=True)
```

### ดู Error Log

```bash
# Error จะแสดงใน Command Prompt
```

### Test Fuzzy Logic

```bash
python fuzzy_logic.py
```

---

## 🌐 Port Management

### เปลี่ยน Port (ถ้า 5000 ถูกใช้)

```python
# แก้ไขใน app.py บรรทัดสุดท้าย:
app.run(debug=True, host='0.0.0.0', port=5001)
```

### ดู Process ที่ใช้ Port

```bash
# Windows:
netstat -ano | findstr :5000
# Mac/Linux:
lsof -i :5000
```

### Kill Process

```bash
# Windows:
taskkill /PID <PID> /F
# Mac/Linux:
kill -9 <PID>
```

---

## 📁 File Management

### ดูไฟล์ในโฟลเดอร์

```bash
# Windows:
dir
# Mac/Linux:
ls -la
```

### เคลียร์ Cache

```bash
# Windows:
rd /s /q __pycache__
# Mac/Linux:
rm -rf __pycache__
```

### ดูขนาดโฟลเดอร์

```bash
# Windows:
dir /s
# Mac/Linux:
du -sh *
```

---

## 🔐 User Management

### สร้าง Admin ใหม่ (ใน Python Shell)

```python
from app import app
from models import db, User

with app.app_context():
    user = User(
        username='newadmin',
        email='newadmin@example.com',
        full_name='New Admin',
        role='admin'
    )
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    print("✅ สร้าง Admin ใหม่สำเร็จ")
```

### เปลี่ยนรหัสผ่าน Admin

```python
from app import app
from models import db, User

with app.app_context():
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('newpassword123')
    db.session.commit()
    print("✅ เปลี่ยนรหัสผ่านสำเร็จ")
```

---

## 📊 ทดสอบระบบ

### ทดสอบกรอกข้อมูล

```
1. Login
2. กรอกข้อมูล
3. ตรวจสอบผลการประเมิน
```

### ทดสอบอัปโหลด Excel

```
1. Login
2. อัปโหลด Excel (ใช้ sample_data.xlsx)
3. ตรวจสอบว่าบันทึกครบ 5 รายการ
```

### ทดสอบ Dashboard

```
1. Login
2. ไป Dashboard
3. ตรวจสอบ:
   - สถิติ 4 บัตร
   - กราฟแนวโน้ม
   - ตารางข้อมูล
```

---

## 🚀 Production Deployment

### เปลี่ยนเป็น Production Mode

```python
# ใน config.py:
DEBUG = False

# ใน app.py:
app.run(host='0.0.0.0', port=5000)
```

### ใช้ MySQL แทน SQLite

```python
# ใน config.py:
SQLALCHEMY_DATABASE_URI = 'mysql://user:password@localhost/water_quality_db'
```

### ติดตั้ง MySQL Driver

```bash
pip install pymysql
```

---

## 🔍 Troubleshooting

### ปัญหา: ModuleNotFoundError

```bash
# แก้: ติดตั้ง dependencies
pip install -r requirements.txt
```

### ปัญหา: Database Error

```bash
# แก้: สร้าง database ใหม่
python init_db.py
```

### ปัญหา: Port Already in Use

```bash
# แก้: เปลี่ยน port หรือ kill process
```

### ปัญหา: Excel Upload Failed

```bash
# แก้: ตรวจสอบรูปแบบไฟล์ Excel
# ต้องมีคอลัมน์ครบตามที่กำหนด
```

### ปัญหา: Fuzzy Logic Error

```bash
# แก้: ตรวจสอบค่าพารามิเตอร์
# ค่าต้องเป็นตัวเลข และไม่เป็น null
```

---

## 📝 Git Commands (ถ้าใช้)

### Initial Commit

```bash
git init
git add .
git commit -m "Initial commit"
```

### Add Remote

```bash
git remote add origin <repository-url>
git push -u origin main
```

### Update Code

```bash
git add .
git commit -m "Update message"
git push
```

### Pull Latest

```bash
git pull origin main
```

---

## 💡 Tips

### 1. ใช้ Virtual Environment เสมอ

```bash
# เพื่อไม่ให้ conflict กับ packages อื่น
```

### 2. Backup Database ก่อนทำงาน

```bash
copy water_quality.db backup/
```

### 3. Test ก่อน Deploy

```bash
# ทดสอบทุกฟีเจอร์ก่อนให้ใช้งานจริง
```

### 4. ดู Log เมื่อมีปัญหา

```bash
# อ่าน Error Message ใน Command Prompt
```

### 5. อัปเดต Dependencies

```bash
pip install --upgrade -r requirements.txt
```

---

## ⌨️ Keyboard Shortcuts

### Command Prompt

- `Ctrl + C` - หยุดโปรแกรม
- `Ctrl + L` หรือ `cls` - Clear Screen
- `Tab` - Auto-complete
- `↑` `↓` - ดูคำสั่งที่เคยใช้

### VS Code

- `Ctrl + ` - เปิด Terminal
- `Ctrl + S` - บันทึกไฟล์
- `Ctrl + F` - ค้นหา
- `Ctrl + /` - Comment

---

## 📞 Quick Reference

**โปรเจค:** Water Quality Assessment System  
**URL:** http://localhost:5000  
**Admin:** admin / admin123  
**Database:** SQLite (water_quality.db)  
**Port:** 5000 (เปลี่ยนได้)

---

**อัปเดตล่าสุด:** 10 พฤศจิกายน 2025
