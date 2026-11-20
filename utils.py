import io
from datetime import datetime
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from models import Certificate, CertificateTemplate, db, utcnow


def allowed_poster(filename, extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in extensions


def save_poster(upload, folder, extensions):
    if not upload or not upload.filename:
        return None
    if not allowed_poster(upload.filename, extensions):
        raise ValueError("Choose a PNG, JPG, JPEG, or WEBP image.")
    suffix = Path(secure_filename(upload.filename)).suffix.lower()
    expected_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}.get(suffix)
    try:
        image = Image.open(upload.stream)
        if image.format != expected_format:
            raise ValueError("The poster file contents do not match its image extension.")
        image.verify()
        upload.stream.seek(0)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("The poster must be a valid PNG, JPG, or WEBP image.") from error
    filename = f"{utcnow().strftime('%Y%m%d%H%M%S%f')}{suffix}"
    upload.save(Path(folder) / filename)
    return filename


def build_qr_image(url):
    image = qrcode.make(url)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def create_certificate(student, event, output_folder):
    existing = Certificate.query.filter_by(student_id=student.id, event_id=event.id).first()
    if existing:
        return existing

    template = event.certificate_template or CertificateTemplate(
        event=event,
        title="Certificate of Participation",
        organization_name="EventEase College",
        signature_name="Event Coordinator",
        design="lavender",
    )
    db.session.add(template)
    db.session.flush()
    certificate_id = f"EE-{utcnow():%Y%m%d}-{student.id:04d}-{event.id:04d}"
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    file_path = output_folder / f"{certificate_id}.pdf"
    page_width, page_height = landscape(letter)
    pdf = canvas.Canvas(str(file_path), pagesize=(page_width, page_height))
    accent = colors.HexColor("#7151b8" if template.design == "lavender" else "#315c81")
    pdf.setFillColor(colors.HexColor("#fbf9ff"))
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    pdf.setStrokeColor(accent)
    pdf.setLineWidth(4)
    pdf.roundRect(24, 24, page_width - 48, page_height - 48, 18, fill=0, stroke=1)
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawCentredString(page_width / 2, page_height - 100, template.organization_name)
    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawCentredString(page_width / 2, page_height - 165, template.title)
    pdf.setFillColor(colors.HexColor("#454052"))
    pdf.setFont("Helvetica", 15)
    pdf.drawCentredString(page_width / 2, page_height - 215, "This certificate is proudly presented to")
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 27)
    pdf.drawCentredString(page_width / 2, page_height - 260, student.full_name)
    pdf.setFillColor(colors.HexColor("#454052"))
    pdf.setFont("Helvetica", 14)
    pdf.drawCentredString(page_width / 2, page_height - 300, "for attending and participating in")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(page_width / 2, page_height - 332, event.title)
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(page_width / 2, page_height - 365, event.event_date.strftime("%B %d, %Y"))
    pdf.setStrokeColor(accent)
    pdf.line(page_width / 2 - 100, 92, page_width / 2 + 100, 92)
    pdf.setFillColor(colors.HexColor("#454052"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawCentredString(page_width / 2, 72, template.signature_name)
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(page_width / 2, 48, f"Certificate ID: {certificate_id}")
    pdf.save()

    certificate = Certificate(
        certificate_id=certificate_id,
        student=student,
        event=event,
        file_path=str(file_path),
    )
    db.session.add(certificate)
    return certificate
