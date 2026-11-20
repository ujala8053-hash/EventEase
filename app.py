import csv
import io
import os
import secrets
from datetime import date, datetime, time
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, send_file,
    send_from_directory, url_for,
)
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from models import (
    Attendance, Certificate, CertificateTemplate, Event, Organizer, Registration,
    User, db,
)
from utils import build_qr_image, create_certificate, save_poster


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    app.config["UPLOAD_FOLDER"] = Path(app.config["UPLOAD_FOLDER"])
    app.config["CERTIFICATE_FOLDER"] = Path(app.config["CERTIFICATE_FOLDER"])
    app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
    app.config["CERTIFICATE_FOLDER"].mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    CSRFProtect(app)
    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.before_request
    def enforce_active_account():
        if current_user.is_authenticated and not current_user.is_active:
            role = current_user.role
            logout_user()
            flash("Your account is no longer active. Please contact the Super Admin.", "warning")
            return redirect(url_for("login", role=role))

    with app.app_context():
        db.create_all()
        email = "superadmin@eventease.com"
        if not User.query.filter_by(email=email).first():
            password = os.environ.get("EVENTEASE_SUPERADMIN_PASSWORD", "EventEase@2026!")
            db.session.add(User(
                full_name="EventEase Super Admin",
                email=email,
                password_hash=generate_password_hash(password),
                role="super_admin",
            ))
            db.session.commit()

    def roles_required(*roles):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapped(*args, **kwargs):
                if current_user.role not in roles:
                    abort(403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def can_manage_event(event):
        return current_user.role == "super_admin" or event.created_by_id == current_user.id

    def event_or_404(event_id):
        return db.get_or_404(Event, event_id)

    def parse_event_form(existing=None):
        try:
            event_date = date.fromisoformat(request.form["event_date"])
            start_time = time.fromisoformat(request.form["start_time"])
            end_time = time.fromisoformat(request.form["end_time"])
            opens = datetime.fromisoformat(request.form["registration_opens"])
            closes = datetime.fromisoformat(request.form["registration_closes"])
            capacity = int(request.form["capacity"])
            fields = {
                "title": request.form["title"].strip(),
                "description": request.form["description"].strip(),
                "venue": request.form["venue"].strip(),
                "event_date": event_date,
                "start_time": start_time,
                "end_time": end_time,
                "registration_opens": opens,
                "registration_closes": closes,
                "category": request.form["category"].strip(),
                "capacity": capacity,
            }
            if not all(fields[key] for key in ("title", "description", "venue", "category")):
                raise ValueError("Complete all required event fields.")
            if capacity < 1:
                raise ValueError("Participant capacity must be at least one.")
            if end_time <= start_time or closes < opens:
                raise ValueError("Check the event times and registration window.")
            if existing and capacity < existing.registration_count:
                raise ValueError("Capacity cannot be lower than the current registration count.")
            return fields
        except (KeyError, ValueError) as error:
            raise ValueError(str(error) or "Enter valid event details.") from error

    @app.context_processor
    def inject_navigation_state():
        return {"today": date.today()}

    @app.route("/")
    def home():
        events = Event.query.filter(Event.event_date >= date.today()).order_by(Event.event_date).limit(3).all()
        return render_template("home.html", events=events)

    @app.route("/about")
    def about():
        return render_template("about.html")

    @app.route("/get-started")
    def get_started():
        return render_template("roles.html")

    @app.route("/register/<role>", methods=["GET", "POST"])
    def register(role):
        if role not in ("student", "admin"):
            abort(404)
        if request.method == "POST":
            name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            if not name or not email or len(password) < 8:
                flash("Enter your name and email and use a password with at least 8 characters.", "danger")
            elif password != request.form.get("confirm_password"):
                flash("The passwords do not match.", "danger")
            elif User.query.filter_by(email=email).first():
                flash("An account already uses that email address.", "danger")
            else:
                user = User(
                    full_name=name,
                    email=email,
                    password_hash=generate_password_hash(password),
                    role=role,
                    is_approved=(role == "student"),
                    department=request.form.get("department", "").strip(),
                )
                if role == "student":
                    user.enrollment_number = request.form.get("enrollment_number", "").strip()
                    user.course_year = request.form.get("course_year", "").strip()
                    if not user.enrollment_number or not user.course_year:
                        flash("Enter your enrollment number and course / year.", "danger")
                        return render_template("register.html", role=role)
                    if User.query.filter_by(enrollment_number=user.enrollment_number).first():
                        flash("That enrollment number is already registered.", "danger")
                        return render_template("register.html", role=role)
                else:
                    user.employee_id = request.form.get("employee_id", "").strip()
                    if not user.employee_id or not user.department:
                        flash("Enter your employee ID and department.", "danger")
                        return render_template("register.html", role=role)
                    if User.query.filter_by(employee_id=user.employee_id).first():
                        flash("That employee ID is already registered.", "danger")
                        return render_template("register.html", role=role)
                db.session.add(user)
                db.session.commit()
                if role == "admin":
                    flash("Your request is submitted. You can sign in once the Super Admin approves it.", "success")
                    return redirect(url_for("login", role="admin"))
                flash("Your student account is ready. Please sign in.", "success")
                return redirect(url_for("login", role="student"))
        return render_template("register.html", role=role)

    @app.route("/login", defaults={"role": "student"}, methods=["GET", "POST"])
    @app.route("/login/<role>", methods=["GET", "POST"])
    def login(role):
        if role not in ("student", "admin", "super_admin"):
            abort(404)
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            user = User.query.filter_by(email=email, role=role).first()
            if not user or not check_password_hash(user.password_hash, request.form.get("password", "")):
                flash("The email or password is incorrect.", "danger")
            elif not user.is_active_account:
                flash("This account is currently deactivated. Contact the Super Admin.", "danger")
            elif role == "admin" and not user.is_approved:
                flash("Your Admin account is awaiting Super Admin approval.", "warning")
            else:
                login_user(user)
                flash(f"Welcome back, {user.full_name.split()[0]}.", "success")
                return redirect(url_for("dashboard"))
        return render_template("login.html", role=role)

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You have been signed out.", "info")
        return redirect(url_for("home"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        if current_user.role in ("admin", "super_admin"):
            query = Event.query.order_by(Event.event_date)
            if current_user.role == "admin":
                query = query.filter_by(created_by_id=current_user.id)
            events = query.limit(8).all()
            pending_admins = User.query.filter_by(role="admin", is_approved=False).order_by(User.created_at).all() if current_user.role == "super_admin" else []
            return render_template("dashboard_admin.html", events=events, pending_admins=pending_admins)
        registrations = Registration.query.filter_by(student_id=current_user.id).all()
        registered_ids = {row.event_id for row in registrations}
        events = Event.query.order_by(Event.event_date).limit(8).all()
        certificates = Certificate.query.filter_by(student_id=current_user.id).order_by(Certificate.issued_at.desc()).limit(3).all()
        return render_template(
            "dashboard_student.html", events=events, registered_ids=registered_ids,
            registrations=registrations, certificates=certificates,
        )

    @app.route("/events")
    def events():
        category = request.args.get("category", "").strip()
        search = request.args.get("q", "").strip()
        query = Event.query
        if category:
            query = query.filter_by(category=category)
        if search:
            query = query.filter(Event.title.ilike(f"%{search}%"))
        listings = query.order_by(Event.event_date).all()
        categories = [row[0] for row in db.session.query(Event.category).distinct().order_by(Event.category).all()]
        return render_template("events.html", events=listings, categories=categories, selected_category=category, search=search)

    @app.route("/events/<int:event_id>")
    def event_detail(event_id):
        event = event_or_404(event_id)
        registered = current_user.is_authenticated and Registration.query.filter_by(
            student_id=current_user.id, event_id=event.id
        ).first() is not None
        return render_template("event_detail.html", event=event, registered=registered)

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.post("/events/<int:event_id>/register")
    @roles_required("student")
    def register_for_event(event_id):
        event = event_or_404(event_id)
        if Registration.query.filter_by(student_id=current_user.id, event_id=event.id).first():
            flash("You are already registered for this event.", "info")
        elif not event.registration_open:
            flash("Registration is not currently open for this event.", "warning")
        elif event.registration_count >= event.capacity:
            flash("This event has reached its participant capacity.", "warning")
        else:
            db.session.add(Registration(student_id=current_user.id, event_id=event.id))
            try:
                db.session.commit()
                flash("You're registered! We look forward to seeing you.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("You are already registered for this event.", "info")
        return redirect(url_for("event_detail", event_id=event.id))

    @app.post("/events/<int:event_id>/cancel")
    @roles_required("student")
    def cancel_registration(event_id):
        event = event_or_404(event_id)
        registration = Registration.query.filter_by(student_id=current_user.id, event_id=event.id).first()
        if registration and not Attendance.query.filter_by(student_id=current_user.id, event_id=event.id).first():
            db.session.delete(registration)
            db.session.commit()
            flash("Your registration has been cancelled.", "success")
        else:
            flash("This registration cannot be cancelled.", "warning")
        return redirect(url_for("event_detail", event_id=event.id))

    @app.route("/admin/events")
    @roles_required("admin", "super_admin")
    def manage_events():
        query = Event.query.order_by(Event.event_date.desc())
        if current_user.role == "admin":
            query = query.filter_by(created_by_id=current_user.id)
        return render_template("manage_events.html", events=query.all())

    @app.route("/admin/events/new", methods=["GET", "POST"])
    @roles_required("admin", "super_admin")
    def create_event():
        if request.method == "POST":
            try:
                fields = parse_event_form()
                poster = save_poster(
                    request.files.get("poster"), app.config["UPLOAD_FOLDER"],
                    app.config["ALLOWED_POSTER_EXTENSIONS"],
                )
                event = Event(**fields, poster_filename=poster, attendance_token=secrets.token_urlsafe(32), created_by_id=current_user.id)
                db.session.add(event)
                db.session.commit()
                flash("Your event has been published.", "success")
                return redirect(url_for("manage_events"))
            except ValueError as error:
                flash(str(error), "danger")
        return render_template("event_form.html", event=None)

    @app.route("/admin/events/<int:event_id>/edit", methods=["GET", "POST"])
    @roles_required("admin", "super_admin")
    def edit_event(event_id):
        event = event_or_404(event_id)
        if not can_manage_event(event):
            abort(403)
        if request.method == "POST":
            try:
                fields = parse_event_form(event)
                poster = save_poster(
                    request.files.get("poster"), app.config["UPLOAD_FOLDER"],
                    app.config["ALLOWED_POSTER_EXTENSIONS"],
                )
                for key, value in fields.items():
                    setattr(event, key, value)
                if poster:
                    event.poster_filename = poster
                db.session.commit()
                flash("Event details updated.", "success")
                return redirect(url_for("manage_events"))
            except ValueError as error:
                flash(str(error), "danger")
        return render_template("event_form.html", event=event)

    @app.post("/admin/events/<int:event_id>/delete")
    @roles_required("admin", "super_admin")
    def delete_event(event_id):
        event = event_or_404(event_id)
        if not can_manage_event(event):
            abort(403)
        db.session.delete(event)
        db.session.commit()
        flash("Event deleted.", "success")
        return redirect(url_for("manage_events"))

    @app.route("/admin/events/<int:event_id>/participants")
    @roles_required("admin", "super_admin")
    def participants(event_id):
        event = event_or_404(event_id)
        if not can_manage_event(event):
            abort(403)
        return render_template("participants.html", event=event)

    @app.route("/admin/events/<int:event_id>/participants.csv")
    @roles_required("admin", "super_admin")
    def export_participants(event_id):
        event = event_or_404(event_id)
        if not can_manage_event(event):
            abort(403)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Full name", "Email", "Enrollment number", "Department", "Registered at", "Attendance"])
        for registration in event.registrations:
            attended = Attendance.query.filter_by(student_id=registration.student_id, event_id=event.id).first()
            writer.writerow([
                registration.student.full_name, registration.student.email,
                registration.student.enrollment_number or "", registration.student.department or "",
                registration.registered_at.isoformat(), attended.attended_at.isoformat() if attended else "",
            ])
        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8-sig")), mimetype="text/csv",
            as_attachment=True, download_name=f"event-{event.id}-participants.csv",
        )

    @app.route("/admin/events/<int:event_id>/organizers", methods=["GET", "POST"])
    @roles_required("admin", "super_admin")
    def organizers(event_id):
        event = event_or_404(event_id)
        if not can_manage_event(event):
            abort(403)
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            if not name or not email or "@" not in email:
                flash("Enter a valid organizer name and email.", "danger")
            else:
                db.session.add(Organizer(
                    event_id=event.id, name=name, email=email,
                    phone=request.form.get("phone", "").strip(),
                ))
                db.session.commit()
                flash("Organizer added.", "success")
                return redirect(url_for("organizers", event_id=event.id))
        return render_template("organizers.html", event=event)

    @app.route("/admin/organizers/<int:organizer_id>/edit", methods=["GET", "POST"])
    @roles_required("admin", "super_admin")
    def edit_organizer(organizer_id):
        organizer = db.get_or_404(Organizer, organizer_id)
        if not can_manage_event(organizer.event):
            abort(403)
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            if not name or not email or "@" not in email:
                flash("Enter a valid organizer name and email.", "danger")
            else:
                organizer.name = name
                organizer.email = email
                organizer.phone = request.form.get("phone", "").strip()
                db.session.commit()
                flash("Organizer details updated.", "success")
                return redirect(url_for("organizers", event_id=organizer.event_id))
        return render_template("organizer_edit.html", organizer=organizer)

    @app.post("/admin/organizers/<int:organizer_id>/delete")
    @roles_required("admin", "super_admin")
    def delete_organizer(organizer_id):
        organizer = db.get_or_404(Organizer, organizer_id)
        if not can_manage_event(organizer.event):
            abort(403)
        event_id = organizer.event_id
        db.session.delete(organizer)
        db.session.commit()
        flash("Organizer removed.", "success")
        return redirect(url_for("organizers", event_id=event_id))

    @app.get("/admin/events/<int:event_id>/qr.png")
    @roles_required("admin", "super_admin")
    def event_qr(event_id):
        event = event_or_404(event_id)
        if not can_manage_event(event):
            abort(403)
        return send_file(
            build_qr_image(url_for("attendance_scan", token=event.attendance_token, _external=True)),
            mimetype="image/png", as_attachment=request.args.get("download") == "1",
            download_name=f"eventease-event-{event.id}-qr.png",
        )

    @app.get("/attendance/scan/<token>")
    @login_required
    def attendance_scan(token):
        event = Event.query.filter_by(attendance_token=token).first_or_404()
        if current_user.role != "student":
            abort(403)
        return render_template("attendance_result.html", event=event)

    @app.route("/student/scanner")
    @roles_required("student")
    def scanner():
        return render_template("scanner.html")

    @app.post("/attendance/mark")
    @roles_required("student")
    def mark_attendance():
        payload = request.get_json(silent=True) or request.form
        token = str(payload.get("token", "")).strip()
        event = Event.query.filter_by(attendance_token=token).first()
        if not event:
            return jsonify(ok=False, message="This EventEase QR code is not valid."), 400
        if not Registration.query.filter_by(student_id=current_user.id, event_id=event.id).first():
            return jsonify(ok=False, message="You must be registered for this event to check in."), 403
        if Attendance.query.filter_by(student_id=current_user.id, event_id=event.id).first():
            return jsonify(ok=False, message="Your attendance is already recorded."), 409
        db.session.add(Attendance(student_id=current_user.id, event_id=event.id))
        try:
            certificate = create_certificate(current_user, event, app.config["CERTIFICATE_FOLDER"])
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(ok=False, message="Your attendance is already recorded."), 409
        except (OSError, ValueError):
            db.session.rollback()
            app.logger.exception("Failed to generate the attendance certificate")
            return jsonify(ok=False, message="Attendance could not be completed. Please contact the event administrator."), 500
        return jsonify(
            ok=True, message="Attendance confirmed. Your certificate is ready!",
            event=event.title, certificate_url=url_for("download_certificate", certificate_id=certificate.certificate_id),
        )

    @app.route("/student/certificates")
    @roles_required("student")
    def my_certificates():
        certificates = Certificate.query.filter_by(student_id=current_user.id).order_by(Certificate.issued_at.desc()).all()
        return render_template("certificates.html", certificates=certificates)

    @app.route("/certificates/<certificate_id>/download")
    @login_required
    def download_certificate(certificate_id):
        certificate = Certificate.query.filter_by(certificate_id=certificate_id).first_or_404()
        if current_user.role == "student" and certificate.student_id != current_user.id:
            abort(403)
        if current_user.role == "admin" and not can_manage_event(certificate.event):
            abort(403)
        path = Path(certificate.file_path)
        if not path.is_file():
            app.logger.error("Certificate file missing for %s", certificate_id)
            abort(404)
        return send_file(path, as_attachment=True, download_name=f"{certificate_id}.pdf", mimetype="application/pdf")

    @app.route("/admin/events/<int:event_id>/certificate-template", methods=["GET", "POST"])
    @roles_required("admin", "super_admin")
    def certificate_template(event_id):
        event = event_or_404(event_id)
        if not can_manage_event(event):
            abort(403)
        template = event.certificate_template
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            organization = request.form.get("organization_name", "").strip()
            signature = request.form.get("signature_name", "").strip()
            design = request.form.get("design", "lavender")
            if not title or not organization or not signature or design not in ("lavender", "blue"):
                flash("Complete each template field.", "danger")
            else:
                if not template:
                    template = CertificateTemplate(event_id=event.id)
                template.title = title
                template.organization_name = organization
                template.signature_name = signature
                template.design = design
                db.session.add(template)
                db.session.commit()
                flash("Certificate template saved. It will be used for future attendance certificates.", "success")
                return redirect(url_for("certificate_template", event_id=event.id))
        return render_template("certificate_template.html", event=event, template=template)

    @app.route("/super-admin/admins")
    @roles_required("super_admin")
    def admin_accounts():
        admins = User.query.filter_by(role="admin").order_by(User.created_at.desc()).all()
        return render_template("admin_accounts.html", admins=admins)

    @app.post("/super-admin/admins/<int:user_id>/<action>")
    @roles_required("super_admin")
    def admin_action(user_id, action):
        user = db.get_or_404(User, user_id)
        if user.role != "admin" or action not in ("approve", "reject", "activate", "deactivate"):
            abort(404)
        if action == "approve":
            user.is_approved = True
            flash(f"{user.full_name}'s Admin account is approved.", "success")
        elif action == "reject":
            db.session.delete(user)
            flash(f"{user.full_name}'s pending request was rejected.", "success")
        else:
            user.is_active_account = action == "activate"
            flash(f"{user.full_name}'s account is now {'active' if user.is_active_account else 'deactivated'}.", "success")
        db.session.commit()
        return redirect(url_for("admin_accounts"))

    @app.route("/super-admin/students")
    @roles_required("super_admin")
    def student_accounts():
        students = User.query.filter_by(role="student").order_by(User.full_name).all()
        return render_template("student_accounts.html", students=students)

    @app.post("/super-admin/students/<int:user_id>/toggle")
    @roles_required("super_admin")
    def toggle_student(user_id):
        student = db.get_or_404(User, user_id)
        if student.role != "student":
            abort(404)
        student.is_active_account = not student.is_active_account
        db.session.commit()
        flash(f"{student.full_name}'s account is now {'active' if student.is_active_account else 'deactivated'}.", "success")
        return redirect(url_for("student_accounts"))

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, message="You don't have permission to access that page."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="We couldn't find that page."), 404

    @app.errorhandler(413)
    def file_too_large(_error):
        flash("That file is too large. Poster uploads must be under 5 MB.", "danger")
        return redirect(request.referrer or url_for("manage_events"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1",port=5001)
