from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint


db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def kolkata_now():
    return datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __table_args__ = (
        CheckConstraint("role IN ('super_admin', 'admin', 'student')", name="ck_user_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_approved = db.Column(db.Boolean, nullable=False, default=True)
    is_active_account = db.Column(db.Boolean, nullable=False, default=True)
    employee_id = db.Column(db.String(60), unique=True)
    enrollment_number = db.Column(db.String(60), unique=True)
    department = db.Column(db.String(120))
    course_year = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    registrations = db.relationship("Registration", back_populates="student", cascade="all, delete-orphan")
    attendances = db.relationship("Attendance", back_populates="student", cascade="all, delete-orphan")
    certificates = db.relationship("Certificate", back_populates="student", cascade="all, delete-orphan")

    @property
    def is_active(self):
        return self.is_active_account and (self.role != "admin" or self.is_approved)


class Event(db.Model):
    __table_args__ = (CheckConstraint("capacity > 0", name="ck_event_capacity_positive"),)

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=False)
    venue = db.Column(db.String(180), nullable=False)
    event_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    registration_opens = db.Column(db.DateTime, nullable=False)
    registration_closes = db.Column(db.DateTime, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    poster_filename = db.Column(db.String(255))
    attendance_token = db.Column(db.String(64), unique=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    registrations = db.relationship("Registration", back_populates="event", cascade="all, delete-orphan")
    organizers = db.relationship("Organizer", back_populates="event", cascade="all, delete-orphan")
    attendances = db.relationship("Attendance", back_populates="event", cascade="all, delete-orphan")
    certificate_template = db.relationship(
        "CertificateTemplate", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )
    certificates = db.relationship("Certificate", back_populates="event", cascade="all, delete-orphan")

    @property
    def status(self):
        today = utcnow().date()
        if self.event_date < today:
            return "Completed"
        if self.event_date == today:
            return "Ongoing"
        return "Upcoming"

    @property
    def registration_count(self):
        return len(self.registrations)

    @property
    def registration_open(self):
        now = kolkata_now()
        return self.registration_opens <= now < self.registration_closes


class Registration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    registered_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint("student_id", "event_id", name="uq_registration_student_event"),)

    student = db.relationship("User", back_populates="registrations")
    event = db.relationship("Event", back_populates="registrations")


class Organizer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    phone = db.Column(db.String(40))
    event = db.relationship("Event", back_populates="organizers")


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    attended_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint("student_id", "event_id", name="uq_attendance_student_event"),)

    student = db.relationship("User", back_populates="attendances")
    event = db.relationship("Event", back_populates="attendances")


class CertificateTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), unique=True, nullable=False)
    title = db.Column(db.String(180), nullable=False, default="Certificate of Participation")
    organization_name = db.Column(db.String(180), nullable=False, default="EventEase College")
    signature_name = db.Column(db.String(120), nullable=False, default="Event Coordinator")
    design = db.Column(db.String(30), nullable=False, default="lavender")
    event = db.relationship("Event", back_populates="certificate_template")


class Certificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    certificate_id = db.Column(db.String(40), unique=True, nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    issued_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    file_path = db.Column(db.String(500), nullable=False)
    __table_args__ = (db.UniqueConstraint("student_id", "event_id", name="uq_certificate_student_event"),)

    student = db.relationship("User", back_populates="certificates")
    event = db.relationship("Event", back_populates="certificates")
