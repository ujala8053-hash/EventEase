import os
import re
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from werkzeug.security import generate_password_hash

from app import create_app
from models import Attendance, Certificate, Event, Organizer, Registration, User, db, kolkata_now, utcnow


class EventEaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "UPLOAD_FOLDER": os.path.join(self.temp_dir.name, "uploads"),
            "CERTIFICATE_FOLDER": os.path.join(self.temp_dir.name, "certificates"),
            "SECRET_KEY": "test-key",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            self.student = User(
                full_name="Taylor Student", email="taylor@example.edu",
                password_hash=generate_password_hash("student-password"),
                role="student", enrollment_number="ENR-100", department="Design",
                course_year="Year 2",
            )
            self.admin = User(
                full_name="Morgan Admin", email="morgan@example.edu",
                password_hash=generate_password_hash("admin-password"),
                role="admin", employee_id="EMP-100", department="Arts",
                is_approved=False,
            )
            db.session.add_all([self.student, self.admin])
            db.session.commit()
            self.student_id = self.student.id
            self.admin_id = self.admin.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def login(self, role, email, password):
        return self.client.post(f"/login/{role}", data={"email": email, "password": password}, follow_redirects=True)

    def test_seed_super_admin_and_pending_admin_cannot_sign_in(self):
        with self.app.app_context():
            seeded = User.query.filter_by(email="superadmin@eventease.com").one()
            self.assertEqual(seeded.role, "super_admin")
            self.assertTrue(seeded.password_hash.startswith("scrypt:"))
        response = self.login("admin", "morgan@example.edu", "admin-password")
        self.assertIn(b"awaiting Super Admin approval", response.data)

    def test_admin_registration_is_pending_until_approved(self):
        response = self.client.post("/register/admin", data={
            "full_name": "Jordan Organizer",
            "email": "jordan@example.edu",
            "employee_id": "EMP-200",
            "department": "Music",
            "password": "organizer-password",
            "confirm_password": "organizer-password",
        }, follow_redirects=True)
        self.assertIn(b"request is submitted", response.data)
        response = self.login("admin", "jordan@example.edu", "organizer-password")
        self.assertIn(b"awaiting Super Admin approval", response.data)

        with self.app.app_context():
            pending_admin = User.query.filter_by(email="jordan@example.edu").one()
            pending_id = pending_admin.id
        self.client.post("/logout")
        self.login("super_admin", "superadmin@eventease.com", "EventEase@2026!")
        approved = self.client.post(f"/super-admin/admins/{pending_id}/approve", follow_redirects=True)
        self.assertEqual(approved.status_code, 200)
        self.client.post("/logout")
        signed_in = self.login("admin", "jordan@example.edu", "organizer-password")
        self.assertIn(b"Your events", signed_in.data)

    def test_admin_approval_and_event_registration_attendance_certificate(self):
        self.login("super_admin", "superadmin@eventease.com", "EventEase@2026!")
        with self.app.app_context():
            admin_id = self.admin_id
        response = self.client.post(f"/super-admin/admins/{admin_id}/approve", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.client.post("/logout")
        self.login("admin", "morgan@example.edu", "admin-password")

        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            opens = utcnow() - timedelta(days=1)
            closes = utcnow() + timedelta(days=1)
            event = Event(
                title="Creative Futures", description="A campus workshop",
                venue="Studio 2", event_date=date.today() + timedelta(days=2),
                start_time=time(10), end_time=time(12), registration_opens=opens,
                registration_closes=closes, category="Workshop", capacity=1,
                attendance_token="secure-event-token-1234567890",
                created_by_id=admin.id,
            )
            db.session.add(event)
            db.session.commit()
            event_id = event.id

        self.client.post("/logout")
        self.login("student", "taylor@example.edu", "student-password")
        response = self.client.post(f"/events/{event_id}/register", follow_redirects=True)
        self.assertIn(b"registered!", response.data)
        with self.app.app_context():
            token = db.session.get(Event, event_id).attendance_token
        response = self.client.post("/attendance/mark", json={"token": token})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("certificate_url", body)
        with self.app.app_context():
            self.assertEqual(Registration.query.filter_by(event_id=event_id).count(), 1)
            self.assertEqual(Attendance.query.filter_by(event_id=event_id).count(), 1)
            certificate = Certificate.query.filter_by(event_id=event_id, student_id=self.student_id).one()
            self.assertTrue(os.path.isfile(certificate.file_path))
            certificate_id = certificate.certificate_id
        certificate_response = self.client.get(body["certificate_url"])
        self.assertEqual(certificate_response.status_code, 200)
        certificate_response.close()
        duplicate = self.client.post("/attendance/mark", json={"token": token})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(certificate_id, body["certificate_url"].split("/")[-2])

    def test_unregistered_student_cannot_check_in(self):
        with self.app.app_context():
            admin = User.query.filter_by(role="super_admin").one()
            event = Event(
                title="Open Studio", description="Open studio day", venue="Hall A",
                event_date=date.today(), start_time=time(9), end_time=time(10),
                registration_opens=utcnow() - timedelta(days=1),
                registration_closes=utcnow() + timedelta(days=1),
                category="Arts", capacity=5, attendance_token="another-secure-token-1234567890",
                created_by_id=admin.id,
            )
            db.session.add(event)
            db.session.commit()
            token = event.attendance_token
        self.login("student", "taylor@example.edu", "student-password")
        response = self.client.post("/attendance/mark", json={"token": token})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["ok"], False)

    def test_registration_window_uses_ist_and_closes_at_deadline(self):
        now_ist = kolkata_now()
        event = Event(
            title="IST registration window", description="Deadline check",
            venue="Campus", event_date=date.today() - timedelta(days=1),
            start_time=time(10), end_time=time(11),
            registration_opens=now_ist - timedelta(minutes=5),
            registration_closes=now_ist + timedelta(minutes=5),
            category="Test", capacity=10, attendance_token="ist-window-test-token-123456789",
            created_by_id=self.admin_id,
        )
        self.assertTrue(event.registration_open)

        event.registration_opens = now_ist + timedelta(minutes=5)
        self.assertFalse(event.registration_open)

        event.registration_opens = now_ist - timedelta(minutes=5)
        event.registration_closes = now_ist - timedelta(microseconds=1)
        self.assertFalse(event.registration_open)

    def test_admin_edit_saves_latest_deadline_and_student_page_displays_it(self):
        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            admin.is_approved = True
            now_ist = kolkata_now()
            event = Event(
                title="Deadline update test", description="Edit this event",
                venue="Campus", event_date=date.today() + timedelta(days=2),
                start_time=time(10), end_time=time(11),
                registration_opens=now_ist - timedelta(days=1),
                registration_closes=now_ist - timedelta(minutes=1),
                category="Test", capacity=10, attendance_token="deadline-edit-test-token-1234567",
                created_by_id=admin.id,
            )
            db.session.add(event)
            db.session.commit()
            event_id = event.id

        self.login("admin", "morgan@example.edu", "admin-password")
        opens = (kolkata_now() - timedelta(minutes=5)).replace(second=0, microsecond=0)
        closes = (kolkata_now() + timedelta(hours=2)).replace(second=0, microsecond=0)
        response = self.client.post(f"/admin/events/{event_id}/edit", data={
            "title": "Deadline update test",
            "description": "Edit this event",
            "venue": "Campus",
            "event_date": (date.today() + timedelta(days=2)).isoformat(),
            "start_time": "10:00",
            "end_time": "11:00",
            "registration_opens": opens.strftime("%Y-%m-%dT%H:%M"),
            "registration_closes": closes.strftime("%Y-%m-%dT%H:%M"),
            "category": "Test",
            "capacity": "10",
        })
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            saved_event = db.session.get(Event, event_id)
            self.assertEqual(saved_event.registration_opens, opens)
            self.assertEqual(saved_event.registration_closes, closes)
            self.assertTrue(saved_event.registration_open)

        self.client.post("/logout")
        self.login("student", "taylor@example.edu", "student-password")
        page = self.client.get(f"/events/{event_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(closes.strftime("%b %d, %Y · %I:%M %p").encode(), page.data)
        self.assertIn(b"Registration closes", page.data)
        self.assertIn(b"Save my seat", page.data)
        registration_response = self.client.post(f"/events/{event_id}/register")
        self.assertEqual(registration_response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(Registration.query.filter_by(event_id=event_id, student_id=self.student_id).count(), 1)

    def test_registration_endpoint_rejects_reached_closing_deadline(self):
        with self.app.app_context():
            super_admin = User.query.filter_by(role="super_admin").one()
            now_ist = kolkata_now()
            event = Event(
                title="Expired registration", description="Deadline passed",
                venue="Campus", event_date=date.today() + timedelta(days=2),
                start_time=time(10), end_time=time(11),
                registration_opens=now_ist - timedelta(hours=1),
                registration_closes=now_ist - timedelta(seconds=1),
                category="Test", capacity=10, attendance_token="expired-window-test-token-1234567",
                created_by_id=super_admin.id,
            )
            db.session.add(event)
            db.session.commit()
            event_id = event.id

        self.login("student", "taylor@example.edu", "student-password")
        response = self.client.post(f"/events/{event_id}/register", follow_redirects=True)
        self.assertIn(b"Registration is not currently open", response.data)
        with self.app.app_context():
            self.assertEqual(Registration.query.filter_by(event_id=event_id, student_id=self.student_id).count(), 0)

    def test_deactivated_account_session_is_revoked(self):
        self.login("student", "taylor@example.edu", "student-password")
        super_admin = self.app.test_client()
        super_admin.post("/login/super_admin", data={
            "email": "superadmin@eventease.com",
            "password": "EventEase@2026!",
        })
        response = super_admin.post(f"/super-admin/students/{self.student_id}/toggle")
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_public_and_role_specific_pages_render(self):
        for path in ("/", "/about", "/get-started", "/events", "/login", "/login/admin", "/login/super_admin", "/register/student", "/register/admin"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        with self.app.app_context():
            admin = db.session.get(User, self.admin_id)
            event = Event(
                title="Campus Design Day", description="Meet and make.",
                venue="Design Studio", event_date=date.today() + timedelta(days=2),
                start_time=time(10), end_time=time(12),
                registration_opens=utcnow() - timedelta(days=1),
                registration_closes=utcnow() + timedelta(days=1), category="Design",
                capacity=20, attendance_token="ui-test-token-12345678901234567890",
                created_by_id=admin.id,
            )
            db.session.add(event)
            db.session.flush()
            organizer = Organizer(event_id=event.id, name="Alex Organizer", email="alex@example.edu")
            db.session.add(organizer)
            db.session.commit()
            event_id = event.id
            organizer_id = organizer.id

        self.login("super_admin", "superadmin@eventease.com", "EventEase@2026!")
        admin_paths = (
            "/admin/events", "/admin/events/new", f"/admin/events/{event_id}/edit",
            f"/admin/events/{event_id}/participants", f"/admin/events/{event_id}/organizers",
            f"/admin/organizers/{organizer_id}/edit", f"/admin/events/{event_id}/certificate-template",
            f"/admin/events/{event_id}/qr.png", "/super-admin/admins", "/super-admin/students",
        )
        for path in admin_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

        self.client.post("/logout")
        self.login("student", "taylor@example.edu", "student-password")
        for path in ("/dashboard", "/student/scanner", "/student/certificates", f"/attendance/scan/{'ui-test-token-12345678901234567890'}"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_login_form_enforces_csrf(self):
        protected_app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "UPLOAD_FOLDER": os.path.join(self.temp_dir.name, "csrf-uploads"),
            "CERTIFICATE_FOLDER": os.path.join(self.temp_dir.name, "csrf-certificates"),
            "SECRET_KEY": "csrf-test-key",
            "WTF_CSRF_ENABLED": True,
        })
        client = protected_app.test_client()
        page = client.get("/login")
        match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
        self.assertIsNotNone(match)
        rejected = client.post("/login", data={"email": "nobody@example.edu", "password": "nope"})
        self.assertEqual(rejected.status_code, 400)
        accepted = client.post("/login", data={
            "email": "nobody@example.edu", "password": "nope",
            "csrf_token": match.group(1).decode(),
        })
        self.assertEqual(accepted.status_code, 200)
        with protected_app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
