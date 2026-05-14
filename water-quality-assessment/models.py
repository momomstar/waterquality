"""
Database Models for Water Quality Assessment System
ใช้ SQLAlchemy สำหรับจัดการฐานข้อมูล
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """
    ตารางผู้ใช้งานระบบ
    """
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(150), nullable=True)
    role = db.Column(db.String(20), default='guest')  # 'admin' or 'guest'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationship
    water_data = db.relationship('WaterQualityData', backref='user', lazy=True)
    
    def set_password(self, password):
        """เข้ารหัสรหัสผ่าน"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """ตรวจสอบรหัสผ่าน"""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class WaterQualityData(db.Model):
    """
    ตารางข้อมูลคุณภาพน้ำทิ้ง
    """
    __tablename__ = 'water_quality_data'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # ข้อมูลทั่วไป
    sample_date = db.Column(db.DateTime, nullable=False)
    sample_location = db.Column(db.String(100), nullable=True)
    pond_name = db.Column(db.String(100), nullable=True)  # ชื่อบ่อ เช่น "บ่อ A", "บ่อ 1"
    sample_type = db.Column(db.String(50), default='ทางออก')  # ก่อนบำบัด/กำลังบำบัด/หลังบำบัด

    # ประเภทอาคาร (มาตรฐาน พ.ศ. 2567): ก / ข / ค / ง
    # อ้างอิง: ประกาศกระทรวงทรัพยากรธรรมชาติและสิ่งแวดล้อม
    #         เรื่อง กำหนดมาตรฐานควบคุมการระบายน้ำทิ้ง พ.ศ. 2567
    building_type = db.Column(db.String(4), default='ก', nullable=False)
    
    # พารามิเตอร์คุณภาพน้ำ (11 ตัวที่ประเมิน)
    pH = db.Column(db.Float, nullable=True)
    BOD = db.Column(db.Float, nullable=True)
    COD = db.Column(db.Float, nullable=True)
    TSS = db.Column(db.Float, nullable=True)
    TDS = db.Column(db.Float, nullable=True)
    oil_grease = db.Column(db.Float, nullable=True)  # O&G
    TKN = db.Column(db.Float, nullable=True)
    sulfide = db.Column(db.Float, nullable=True)
    TCB = db.Column(db.Float, nullable=True)
    FCB = db.Column(db.Float, nullable=True)
    chlorine = db.Column(db.Float, nullable=True)  # Cl2
    
    # พารามิเตอร์เสริม (ไม่ประเมิน แต่เก็บไว้)
    ammonium = db.Column(db.Float, nullable=True)  # NH₄⁺
    dissolved_oxygen = db.Column(db.Float, nullable=True)  # DO
    
    # บันทึกเวลา
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    evaluation = db.relationship('EvaluationResult', backref='water_data', uselist=False, lazy=True)
    
    def to_dict(self):
        """แปลงข้อมูลเป็น dictionary"""
        return {
            'id': self.id,
            'sample_date': self.sample_date.strftime('%Y-%m-%d %H:%M:%S') if self.sample_date else None,
            'sample_location': self.sample_location,
            'pond_name': self.pond_name,
            'sample_type': self.sample_type,
            'building_type': self.building_type,
            'pH': self.pH,
            'BOD': self.BOD,
            'COD': self.COD,
            'TSS': self.TSS,
            'TDS': self.TDS,
            'O&G': self.oil_grease,
            'TKN': self.TKN,
            'Sulfide': self.sulfide,
            'TCB': self.TCB,
            'FCB': self.FCB,
            'Cl2': self.chlorine,
            'NH4': self.ammonium,
            'DO': self.dissolved_oxygen
        }
    
    def __repr__(self):
        return f'<WaterQualityData {self.id} - {self.sample_date}>'


class EvaluationResult(db.Model):
    """
    ตารางผลการประเมินคุณภาพน้ำ
    """
    __tablename__ = 'evaluation_results'
    
    id = db.Column(db.Integer, primary_key=True)
    water_data_id = db.Column(db.Integer, db.ForeignKey('water_quality_data.id'), nullable=False)
    
    # ผลการประเมินโดยรวม
    overall_status = db.Column(db.String(20), nullable=False)  # Pass, Near Limit, Fail
    overall_score = db.Column(db.Float, nullable=False)
    overall_message = db.Column(db.String(255), nullable=True)
    
    # สถิติการประเมิน
    pass_count = db.Column(db.Integer, default=0)
    near_limit_count = db.Column(db.Integer, default=0)
    fail_count = db.Column(db.Integer, default=0)
    total_parameters = db.Column(db.Integer, default=0)
    
    # ผลการประเมินแต่ละพารามิเตอร์ (JSON format)
    pH_result = db.Column(db.JSON, nullable=True)
    BOD_result = db.Column(db.JSON, nullable=True)
    COD_result = db.Column(db.JSON, nullable=True)
    TSS_result = db.Column(db.JSON, nullable=True)
    TDS_result = db.Column(db.JSON, nullable=True)
    oil_grease_result = db.Column(db.JSON, nullable=True)
    TKN_result = db.Column(db.JSON, nullable=True)
    sulfide_result = db.Column(db.JSON, nullable=True)
    TCB_result = db.Column(db.JSON, nullable=True)
    FCB_result = db.Column(db.JSON, nullable=True)
    chlorine_result = db.Column(db.JSON, nullable=True)
    
    # บันทึกเวลา
    evaluated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EvaluationResult {self.id} - {self.overall_status}>'


def init_db(app):
    """
    เริ่มต้นฐานข้อมูล
    """
    db.init_app(app)
    
    with app.app_context():
        # สร้างตารางทั้งหมด
        db.create_all()

        # ===== Migration: เพิ่ม column building_type ถ้ายังไม่มี =====
        # SQLite รองรับ ALTER TABLE ADD COLUMN ผ่าน raw SQL
        try:
            from sqlalchemy import text, inspect
            inspector = inspect(db.engine)
            cols = [c['name'] for c in inspector.get_columns('water_quality_data')]
            if 'building_type' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE water_quality_data "
                        "ADD COLUMN building_type VARCHAR(4) DEFAULT 'ก' NOT NULL"
                    ))
                print("✅ Migration: เพิ่ม column 'building_type' ในตาราง water_quality_data สำเร็จ")
        except Exception as e:
            print(f"⚠️  Migration warning (building_type): {e}")

        # สร้าง Admin account ถ้ายังไม่มี
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@waterquality.com',
                full_name='System Administrator',
                role='admin'
            )
            admin.set_password('admin123')  # รหัสผ่านเริ่มต้น
            db.session.add(admin)
            db.session.commit()
            print("✅ สร้าง Admin account สำเร็จ (username: admin, password: admin123)")


def create_sample_data(app):
    """
    สร้างข้อมูลตัวอย่างสำหรับทดสอบ
    """
    with app.app_context():
        # ตรวจสอบว่ามีข้อมูลแล้วหรือยัง
        if WaterQualityData.query.count() > 0:
            print("มีข้อมูลตัวอย่างอยู่แล้ว")
            return
        
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("ไม่พบ Admin account")
            return
        
        # สร้างข้อมูลตัวอย่าง 2 บ่อ x 3 ช่วงเวลา x 3 วัน = 18 รายการ
        from datetime import datetime, timedelta
        base_date = datetime(2025, 1, 15, 10, 0)
        
        ponds = ['บ่อ A', 'บ่อ B']
        sample_types = ['ก่อนบำบัด', 'กำลังบำบัด', 'หลังบำบัด']
        
        for day in range(3):
            current_date = base_date + timedelta(days=day*5)
            
            for pond in ponds:
                # ก่อนบำบัด (ค่าสูง)
                before = WaterQualityData(
                    user_id=admin.id,
                    sample_date=current_date,
                    sample_location='โรงบำบัดน้ำเสีย',
                    pond_name=pond,
                    sample_type='ก่อนบำบัด',
                    pH=6.8 + (day * 0.1),
                    BOD=80 + (day * 5),
                    COD=180 + (day * 10),
                    TSS=120 + (day * 5),
                    TDS=1200 + (day * 50),
                    oil_grease=25 + (day * 2),
                    TKN=40 + (day * 2),
                    sulfide=0.5,
                    TCB=8000 + (day * 200),
                    FCB=1500 + (day * 100),
                    chlorine=0
                )
                db.session.add(before)
                
                # กำลังบำบัด
                inprocess = WaterQualityData(
                    user_id=admin.id,
                    sample_date=current_date + timedelta(hours=6),
                    sample_location='โรงบำบัดน้ำเสีย',
                    pond_name=pond,
                    sample_type='กำลังบำบัด',
                    pH=7.2 + (day * 0.1),
                    BOD=45 + (day * 3),
                    COD=110 + (day * 5),
                    TSS=60 + (day * 3),
                    TDS=950 + (day * 30),
                    oil_grease=12 + day,
                    TKN=25 + day,
                    sulfide=0.2,
                    TCB=5000 + (day * 150),
                    FCB=900 + (day * 50),
                    chlorine=0.3,
                    dissolved_oxygen=3.5 + (day * 0.2)  # DO สำคัญในช่วงนี้
                )
                db.session.add(inprocess)
                
                # หลังบำบัด (ค่าต่ำ - ผ่านมาตรฐาน)
                after = WaterQualityData(
                    user_id=admin.id,
                    sample_date=current_date + timedelta(hours=12),
                    sample_location='โรงบำบัดน้ำเสีย',
                    pond_name=pond,
                    sample_type='หลังบำบัด',
                    pH=7.5 + (day * 0.05),
                    BOD=15 + day,
                    COD=95 + (day * 3),
                    TSS=22 + day,
                    TDS=800 + (day * 20),
                    oil_grease=16 + day,
                    TKN=28 + day,
                    sulfide=0,
                    TCB=3800 + (day * 100),
                    FCB=750 + (day * 30),
                    chlorine=0.7 + (day * 0.05)
                )
                db.session.add(after)
                db.session.flush()
                
                # ประเมินเฉพาะหลังบำบัด
                from fuzzy_logic import WaterQualityFuzzySystem
                fuzzy_system = WaterQualityFuzzySystem()
                
                parameters = {
                    'pH': after.pH,
                    'BOD': after.BOD,
                    'COD': after.COD,
                    'TSS': after.TSS,
                    'TDS': after.TDS,
                    'O&G': after.oil_grease,
                    'TKN': after.TKN,
                    'Sulfide': after.sulfide,
                    'TCB': after.TCB,
                    'FCB': after.FCB,
                    'Cl2': after.chlorine
                }
                
                evaluation = fuzzy_system.evaluate_overall(parameters)
                
                from models import EvaluationResult
                result = EvaluationResult(
                    water_data_id=after.id,
                    overall_status=evaluation['overall_status'],
                    overall_score=evaluation['overall_score'],
                    overall_message=evaluation['overall_message'],
                    pass_count=evaluation['pass_count'],
                    near_limit_count=evaluation['near_limit_count'],
                    fail_count=evaluation['fail_count'],
                    total_parameters=evaluation['total_parameters'],
                    pH_result=evaluation['parameter_results'].get('pH'),
                    BOD_result=evaluation['parameter_results'].get('BOD'),
                    COD_result=evaluation['parameter_results'].get('COD'),
                    TSS_result=evaluation['parameter_results'].get('TSS'),
                    TDS_result=evaluation['parameter_results'].get('TDS'),
                    oil_grease_result=evaluation['parameter_results'].get('O&G'),
                    TKN_result=evaluation['parameter_results'].get('TKN'),
                    sulfide_result=evaluation['parameter_results'].get('Sulfide'),
                    TCB_result=evaluation['parameter_results'].get('TCB'),
                    FCB_result=evaluation['parameter_results'].get('FCB'),
                    chlorine_result=evaluation['parameter_results'].get('Cl2')
                )
                db.session.add(result)
        
        db.session.commit()
        print(f"✅ สร้างข้อมูลตัวอย่าง 2 บ่อ x 3 ช่วง x 3 วัน = 18 รายการสำเร็จ")
