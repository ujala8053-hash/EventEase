# EventEase

EventEase is a Flask college event platform with separate Student, Admin and Super Admin access. It includes admin approval, event publishing and registration, attendance QR codes, organizer and participant management, and automatic PDF certificates after verified student check-in.

## Requirements

- Python 3.10 or newer
- pip
- A modern browser; camera-based QR scanning requires HTTPS or `localhost`

## Install and run

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). SQLite tables and the initial Super Admin account are created automatically when the app starts. Uploaded posters, the SQLite database and generated certificates are stored in the project directory.

### Initial Super Admin

- Email: `superadmin@eventease.com`
- Initial password: `EventEase@2026!`

Set `EVENTEASE_SUPERADMIN_PASSWORD` before the first launch to choose a different initial password. The seed account is only created when its email does not already exist. Change the initial password after the first sign-in and do not use the development defaults in a public deployment.

For deployment, set a long random `EVENTEASE_SECRET_KEY`, configure `DATABASE_URL` if needed, disable debug mode and serve the app behind an HTTPS-capable production WSGI server. Camera access is restricted by browsers to secure contexts (HTTPS or localhost).

## Accounts and roles

- **Student:** register with enrollment, course/year and department details; accounts are active immediately.
- **Admin:** register with employee/teacher ID and department; access remains pending until approved by the Super Admin.
- **Super Admin:** seeded college authority account; has access to all event-admin functions and manages Admin and Student accounts.

No volunteer or additional roles are provided.

## Event and certificate workflow

1. An Admin or Super Admin creates and publishes an event, optionally uploading a PNG, JPG, JPEG or WEBP poster (maximum 5 MB).
2. The organizer can manage the event's organizers, participants, CSV export, QR code and certificate design from **Manage events**.
3. Students register during the event's registration window while seats are available.
4. At the event, the student signs in and uses **Scan attendance QR** to scan the event QR with their device camera. They can also open the QR link while signed in and confirm check-in.
5. The server validates the QR token, Student role and event registration, then records attendance once and generates an associated PDF certificate. Students can immediately download it from **My certificates**.

Attendance and certificate records have database uniqueness constraints to prevent duplicates. QR tokens are generated using a cryptographically secure random source. The scanner library and Bootstrap are loaded from their public CDNs.

## Tests

Install the requirements and run:

```powershell
python -m unittest discover -s tests -v
```
