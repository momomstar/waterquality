"""
Configuration file for Water Quality Assessment System
"""

import os


class Config:
    """การตั้งค่าพื้นฐานของระบบ"""
    
    # Secret Key สำหรับ Flask Session (ควรเปลี่ยนในระบบจริง)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-only-key-change-me'
    
    # ตั้งค่า SQLAlchemy
    # สำหรับใช้ SQLite (ไม่ต้องติดตั้ง MySQL ก็ได้)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///water_quality.db'
    
    # ปิด track modifications เพื่อประหยัด memory
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # ตั้งค่าการอัปโหลดไฟล์
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # จำกัดขนาดไฟล์ 16MB
    ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
    
    # จำนวนรายการต่อหน้า (สำหรับ pagination)
    ITEMS_PER_PAGE = 10


class DevelopmentConfig(Config):
    """การตั้งค่าสำหรับการพัฒนา"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """การตั้งค่าสำหรับใช้งานจริง"""
    DEBUG = False
    TESTING = False
    
    # ใช้ MySQL ในระบบจริง (ต้องติดตั้ง MySQL ก่อน)
    # SQLALCHEMY_DATABASE_URI = 'mysql://username:password@localhost/water_quality_db'


# เลือก Config ตามสภาพแวดล้อม
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
