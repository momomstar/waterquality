"""
Script สำหรับเริ่มต้นฐานข้อมูล
รันไฟล์นี้เพื่อสร้างฐานข้อมูลและข้อมูลเริ่มต้น
"""

from app import app
from models import db, init_db, create_sample_data

print("=" * 60)
print("🚀 เริ่มต้นฐานข้อมูล Water Quality Assessment System")
print("=" * 60)

# เริ่มต้นฐานข้อมูล
print("\n📦 กำลังสร้างตารางในฐานข้อมูล...")
init_db(app)

# สร้างข้อมูลตัวอย่าง
print("\n📝 กำลังสร้างข้อมูลตัวอย่าง...")
create_sample_data(app)

print("\n" + "=" * 60)
print("✅ เริ่มต้นฐานข้อมูลเรียบร้อย!")
print("=" * 60)
print("\n📌 บัญชี Admin:")
print("   ชื่อผู้ใช้: admin")
print("   รหัสผ่าน: admin123")
print("\n🚀 รันโปรแกรมด้วยคำสั่ง: python app.py")
print("=" * 60)
