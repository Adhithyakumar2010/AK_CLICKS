from werkzeug.exceptions import HTTPException
import base64
import hashlib
import hmac
import html
import io
import json
import os
import random
import re
import secrets
import sqlite3
import struct
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import qrcode
import qrcode.image.svg
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_mail import Mail, Message
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'ak_clicks_photography_production_secret_key_2026')

# CSRF Protection & State Machine Helpers
def generate_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]

def validate_csrf(token):
    session_token = session.get("csrf_token")
    if not session_token or not token:
        return False
    return hmac.compare_digest(session_token, token)

@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if app.config.get("TESTING") and not app.config.get("WTF_CSRF_ENABLED", True):
            return None
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or request.headers.get("X-CSRFToken")
        if not validate_csrf(token):
            abort(403)


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf_token())

VALID_STATUS_TRANSITIONS = {
    "Pending": {"Pending", "Approved", "Declined", "Cancelled"},
    "Approved": {"Approved", "Completed", "Cancelled"},
    "Completed": {"Completed"},
    "Declined": {"Declined"},
    "Cancelled": {"Cancelled"}
}

def is_valid_status_transition(current_status, new_status):
    allowed = VALID_STATUS_TRANSITIONS.get(current_status, {current_status})
    return new_status in allowed

def validate_booking_date_str(date_str, allow_past=False):
    if not date_str or not isinstance(date_str, str):
        return False, "Booking date is required."
    date_str = date_str.strip()
    try:
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return False, "Please enter a valid date in YYYY-MM-DD format."
    
    if not allow_past and parsed_date < date.today():
        return False, "Booking date cannot be in the past."
    return True, parsed_date.isoformat()


app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-before-production")
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() in ("true", "1", "on")
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "false").lower() in ("true", "1", "on")
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=1)

# Password Strength Validator
def validate_password_strength(password):
    """
    Validate password strength:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one number."
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-\=\+]', password):
        return False, "Password must contain at least one special character."
    return True, "Password meets strength requirements."

# Developer-friendly Rate Limiter Store
RATE_LIMIT_STORE = {}

def is_rate_limited(ip, endpoint, max_requests=30, window_seconds=60):
    """Check if client IP exceeds max requests within window_seconds."""
    now = time.time()
    key = f"{ip}:{endpoint}"
    timestamps = RATE_LIMIT_STORE.get(key, [])
    timestamps = [t for t in timestamps if now - t < window_seconds]
    if len(timestamps) >= max_requests:
        RATE_LIMIT_STORE[key] = timestamps
        return True
    timestamps.append(now)
    RATE_LIMIT_STORE[key] = timestamps
    return False

mail = Mail(app)

def send_email_with_logs(recipient, subject, body):
    print(f"Customer Email: {recipient}", flush=True)
    print("Connecting to SMTP...", flush=True)
    try:
        sender = app.config.get("MAIL_DEFAULT_SENDER") or "noreply@akclicks.com"
        msg = Message(subject=subject, recipients=[recipient], body=body, sender=sender)
        mail.send(msg)
        print("Email Sent Successfully", flush=True)
        return True, None
    except Exception as e:
        print(f"SMTP Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False, str(e)

BOOKING_DEPOSIT = int(os.environ.get("BOOKING_DEPOSIT", "2000"))
UPI_ID = os.environ.get("UPI_ID", "your-upi-id@bank")
FAVICON_VERSION = "20260727"
BOOKING_PACKAGES = {
    "Essential": 5000,
    "Signature": 10000,
    "Premium": 18000,
}

PRODUCTS = [
    {"id": "armor-of-light", "name": "The Armor of Light", "category": "Historical novel", "price": 299, "image": "images/story-store/trick-treat1-img.jpeg", "description": "A sweeping historical story from Ken Follett."},
    {"id": "real-ghost-stories", "name": "Real Ghost Stories", "category": "True incidents", "price": 592, "image": "images/story-store/trick-treat2-img.jpg", "description": "A chilling collection for late-night readers."},
    {"id": "harry-potter", "name": "Harry Potter", "category": "Fantasy novel", "price": 784, "image": "images/story-store/trick-treat3-img.jpeg", "description": "Magic, mystery and adventure in one classic edition."},
    {"id": "end-of-loneliness", "name": "The End of Loneliness", "category": "Romantic novel", "price": 548, "image": "images/story-store/trick-treat4-img.jpg", "description": "An affecting story about memory, love and connection."},
    {"id": "lord-of-rings", "name": "The Lord of the Rings", "category": "Fantasy classic", "price": 989, "image": "images/story-store/trick-treat5-img.jpg", "description": "The complete, timeless adventure from Middle-earth."},
    {"id": "verity", "name": "Verity", "category": "Psychological thriller", "price": 536, "image": "images/story-store/trick-treat6-img.jpg", "description": "A twist-filled page-turner from Colleen Hoover."},
]

DATABASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "bookings.db"))
TEST_DATABASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_bookings.db"))

def db_connection():
    db_file = TEST_DATABASE_PATH if app.config.get("TESTING") else DATABASE_PATH
    conn = sqlite3.connect(db_file, timeout=20.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    return conn

def favicon_head_markup():
    """Return one cache-busted favicon set for every HTML page."""
    icon_url = url_for("static", filename="images/favicon.ico", v=FAVICON_VERSION)
    png_url = url_for("static", filename="images/favicon.png", v=FAVICON_VERSION)
    return (
        f'<link rel="icon" href="{icon_url}" sizes="any" type="image/x-icon">'
        f'<link rel="icon" href="{png_url}" sizes="32x32" type="image/png">'
    )

@app.after_request
def add_security_headers_and_favicon(response):
    """Apply security headers and keep favicon markup identical across templates."""
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data: blob:; "
        "img-src 'self' data: blob: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com;"
    )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    if response.mimetype == "text/html":
        try:
            page = response.get_data(as_text=True)
            if "</head>" in page and "images/favicon.ico" not in page:
                response.set_data(page.replace("</head>", favicon_head_markup() + "</head>", 1))
        except Exception:
            pass
    return response

@app.errorhandler(404)
def page_not_found(e):
    return render_template("error_404.html"), 404

@app.errorhandler(403)
def access_forbidden(e):
    return render_template("error_403.html"), 403

@app.errorhandler(500)
def internal_server_error(e):
    return render_template("error_500.html"), 500

def add_column_if_missing(conn, table, column, definition):
    if column not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def queue_notification(conn, recipient, channel, subject, body):
    conn.execute("INSERT INTO notifications (recipient, channel, subject, body) VALUES (?, ?, ?, ?)", (recipient, channel, subject, body))

def init_db():
    with db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,service TEXT NOT NULL,booking_date TEXT NOT NULL,location TEXT,message TEXT,status TEXT NOT NULL DEFAULT 'Pending',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date_status ON bookings(booking_date, status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_email ON bookings(email);")
        
        # Verify no active duplicate booking dates exist before creating the unique index
        dups = conn.execute("""
            SELECT booking_date FROM bookings 
            WHERE status NOT IN ('Declined', 'Cancelled') 
            GROUP BY booking_date HAVING COUNT(*) > 1
        """).fetchall()
        if not dups:
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_booking_date 
                ON bookings(booking_date) 
                WHERE status NOT IN ('Declined', 'Cancelled');
            """)

        conn.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT,recipient TEXT NOT NULL,channel TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Queued',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        for table in ("bookings",):
            add_column_if_missing(conn, table, "payment_status", "TEXT NOT NULL DEFAULT 'Unpaid'")
            add_column_if_missing(conn, table, "payment_method", "TEXT")

    # NEW
        add_column_if_missing(conn, "customers", "phone", "TEXT")
        add_column_if_missing(conn, "customers", "address", "TEXT")
        add_column_if_missing(conn, "customers", "profile_image", "TEXT DEFAULT 'images/default-profile.png'")
        add_column_if_missing(conn, "customers", "is_verified", "INTEGER DEFAULT 1")
        add_column_if_missing(conn, "customers", "verification_token", "TEXT")
        add_column_if_missing(conn, "customers", "reset_token", "TEXT")
        add_column_if_missing(conn, "customers", "reset_token_expiry", "DATETIME")
        add_column_if_missing(conn, "notifications", "is_read", "INTEGER NOT NULL DEFAULT 0")



        add_column_if_missing(conn, "customers", "is_blocked", "INTEGER DEFAULT 0")

def payment_record(kind, record_id):
    if kind != "booking": abort(404)
    with db_connection() as conn:
        record = conn.execute("SELECT * FROM bookings WHERE id=?", (record_id,)).fetchone()
    if record is None: abort(404)
    package = record["service"].rsplit(" — ", 1)[-1]
    return "bookings", record, BOOKING_PACKAGES.get(package, BOOKING_DEPOSIT)

def pending_booking():
    data = session.get("pending_booking")
    required = {"name", "email", "phone", "service", "package", "location"}
    return data if isinstance(data, dict) and required.issubset(data) else None

@app.route("/")
def home(): return render_template("index.html", year=datetime.now().year)

@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="images/favicon.ico", v=FAVICON_VERSION))

@app.route("/availability")
def availability():
    date = request.args.get("date", "")
    with db_connection() as conn:
        statuses = [row["status"] for row in conn.execute("SELECT status FROM bookings WHERE booking_date=? AND status NOT IN ('Declined', 'Cancelled')", (date,)).fetchall()]
    available = not statuses
    return jsonify({"date": date, "available": available, "statuses": statuses, "message": "Available to book" if available else "This date is currently unavailable."})

@app.route("/booking-calendar")
def booking_calendar():
    if not pending_booking():
        flash("Complete your booking details before selecting a date.", "error")
        return redirect(url_for("home") + "#booking")
    return render_template("booking_calendar.html", year=datetime.now().year)

@app.route("/api/booking-calendar")
def booking_calendar_data():
    month = request.args.get("month", "")
    try:
        start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        return jsonify({"error": "Use a valid month in YYYY-MM format."}), 400

    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    with db_connection() as conn:
        rows = conn.execute(
            "SELECT booking_date, status FROM bookings WHERE booking_date >= ? AND booking_date < ? AND status NOT IN ('Declined', 'Cancelled')",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    # Only date and status are exposed: visitors never see another customer's details.
    events = [{"date": row["booking_date"], "status": row["status"]} for row in rows]
    return jsonify({"month": month, "events": events})

@app.route("/book", methods=["POST"])
def book():
    fields = {key: request.form.get(key, "").strip() for key in ("name", "email", "phone", "service", "package", "location", "message")}
    if not all(fields[key] for key in ("name", "email", "phone", "service", "package", "location")):
        flash("Please complete all required booking details.", "error")
        return redirect(url_for("home") + "#booking")
    if fields["package"] not in BOOKING_PACKAGES:
        flash("Please choose a valid photography package.", "error")
        return redirect(url_for("home") + "#booking")
    fields["email"] = fields["email"].lower()
    session["pending_booking"] = fields
    session.modified = True
    return redirect(url_for("booking_calendar"))

@app.route("/booking/select-date", methods=["POST"])
def select_booking_date():
    details = pending_booking()
    if not details:
        flash("Your booking details have expired. Please start again.", "error")
        return redirect(url_for("home") + "#booking")
    selected_date = request.form.get("booking_date", "").strip()
    try:
        event_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
    except ValueError:
        flash("Please choose a valid event date.", "error")
        return redirect(url_for("booking_calendar"))
    if event_date < date.today():
        flash("Please choose a future event date.", "error")
        return redirect(url_for("booking_calendar"))
    with db_connection() as conn:
        unavailable = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_date=? AND status NOT IN ('Declined', 'Cancelled') LIMIT 1",
            (selected_date,),
        ).fetchone()
        if unavailable:
            flash("That date has just become unavailable. Please select another date.", "error")
            return redirect(url_for("booking_calendar"))
    details["booking_date"] = selected_date
    session["pending_booking"] = details
    session.modified = True
    return redirect(url_for("pending_booking_payment"))

@app.route("/booking/payment")
def pending_booking_payment():
    details = pending_booking()
    if not details or not details.get("booking_date"):
        flash("Choose an available date before continuing to payment.", "error")
        return redirect(url_for("booking_calendar"))
    return render_template(
        "booking_payment.html",
        booking=details,
        amount=BOOKING_PACKAGES[details["package"]],
        upi_id=UPI_ID,
    )

@app.route("/booking/payment/qr")
def pending_booking_payment_qr():
    details = pending_booking()
    if not details or not details.get("booking_date"):
        abort(404)
    amount = BOOKING_PACKAGES[details["package"]]
    payload = "upi://pay?" + urlencode({"pa": UPI_ID, "pn": "AK CLICKS", "am": amount, "cu": "INR", "tn": "AK-PENDING-BOOKING"})
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    output = io.BytesIO(); image.save(output)
    return Response(output.getvalue(), mimetype="image/svg+xml")

@app.route("/booking/payment/confirm", methods=["POST"])
def confirm_pending_booking_payment():
    if not (app.config.get("TESTING") and not app.config.get("WTF_CSRF_ENABLED", True)):
        if not validate_csrf(request.form.get("csrf_token")):
            flash("Security token validation failed. Please try again.", "error")
            return redirect(url_for("pending_booking_payment"))
    details = pending_booking()
    method = request.form.get("method")
    if not details or not details.get("booking_date"):
        flash("Your booking session has expired. Please start again.", "error")
        return redirect(url_for("home") + "#booking")
    if method not in {"upi", "netbanking", "card"}:
        flash("Choose a valid payment method.", "error")
        return redirect(url_for("pending_booking_payment"))
        
    is_valid_date, date_res = validate_booking_date_str(details["booking_date"])
    if not is_valid_date:
        flash(date_res, "error")
        return redirect(url_for("booking_calendar"))
        
    service = f"{details['service']} — {details['package']}"
    message = f"Package: {details['package']}\n{details['message']}".strip()
    
    conn = db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        unavailable = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_date=? AND status NOT IN ('Declined', 'Cancelled') LIMIT 1",
            (date_res,),
        ).fetchone()
        if unavailable:
            conn.rollback()
            flash("That date is no longer available. Please choose another date.", "error")
            return redirect(url_for("booking_calendar"))
            
        cursor = conn.execute(
            "INSERT INTO bookings (name,email,phone,service,booking_date,location,message,payment_status,payment_method,status) VALUES (?,?,?,?,?,?,?,?,?,'Pending')",
            (details["name"], details["email"], details["phone"], service, date_res, details["location"], message, "Payment submitted (test)", method),
        )
        booking_id = cursor.lastrowid
        queue_notification(conn, details["email"], "email", "Booking enquiry received", f"Your {service} enquiry is recorded. Booking reference: {booking_id}.")
        queue_notification(conn, details["email"], "whatsapp", "Payment submitted", f"Payment submission received for booking #{booking_id}. This is test mode.")
        conn.commit()
    except (sqlite3.IntegrityError, sqlite3.OperationalError):
        conn.rollback()
        flash("That date was concurrently reserved by another customer. Please select another date.", "error")
        return redirect(url_for("booking_calendar"))
    finally:
        conn.close()

    session.pop("pending_booking", None)
    return render_template("confirmation.html", kind="booking", record_id=booking_id, paid=True, year=datetime.now().year)


@app.route("/customer/booking/<int:booking_id>")
def customer_booking_detail(booking_id):
    if not session.get("customer_id"):
        return redirect(url_for("account"))
    conn = db_connection()
    try:
        customer = conn.execute("SELECT email FROM customers WHERE id=?", (session["customer_id"],)).fetchone()
        if not customer:
            abort(403)
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            abort(404)
        if booking["email"].lower() != customer["email"].lower():
            abort(403)
        return render_template("confirmation.html", kind="booking", record_id=booking_id, paid=(booking["payment_status"] != "Unpaid"), year=datetime.now().year)
    finally:
        conn.close()

@app.route("/customer/booking/<int:booking_id>/cancel", methods=["POST"])
def customer_cancel_booking(booking_id):
    if not session.get("customer_id"):
        return redirect(url_for("account"))
    if not validate_csrf(request.form.get("csrf_token")):
        abort(403)
        
    conn = db_connection()
    try:
        customer = conn.execute("SELECT email FROM customers WHERE id=?", (session["customer_id"],)).fetchone()
        if not customer:
            abort(403)
            
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            flash("Booking record not found.", "error")
            return redirect(url_for("customer_bookings"))
            
        # IDOR Security Check
        if booking["email"].lower() != customer["email"].lower():
            flash("Unauthorized attempt to cancel another customer's booking.", "error")
            abort(403)
            
        # State Machine Transition Validation
        if not is_valid_status_transition(booking["status"], "Cancelled") or booking["status"] in {"Completed", "Declined", "Cancelled"}:
            flash(f"Booking #{booking_id} cannot be cancelled because its current status is '{booking['status']}'.", "error")
            return redirect(url_for("customer_bookings"))
            
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE bookings SET status='Cancelled' WHERE id=?", (booking_id,))
        queue_notification(conn, customer["email"], "email", "Booking Cancelled", f"Your booking #{booking_id} for date {booking['booking_date']} has been cancelled.")
        conn.commit()
        flash(f"Booking #{booking_id} has been cancelled successfully. The date {booking['booking_date']} is now available.", "success")
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        flash("An error occurred while cancelling your booking.", "error")
    finally:
        conn.close()
        
    return redirect(url_for("customer_bookings"))

@app.route("/customer/booking/<int:booking_id>/reschedule", methods=["POST"])
def customer_reschedule_booking(booking_id):
    if not session.get("customer_id"):
        return redirect(url_for("account"))
    if not validate_csrf(request.form.get("csrf_token")):
        abort(403)
        
    conn = db_connection()
    try:
        customer = conn.execute("SELECT email FROM customers WHERE id=?", (session["customer_id"],)).fetchone()
        if not customer:
            abort(403)
            
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            flash("Booking record not found.", "error")
            return redirect(url_for("customer_bookings"))
            
        # IDOR Security Check MUST occur before payload validation
        if booking["email"].lower() != customer["email"].lower():
            flash("Unauthorized attempt to modify another customer's booking.", "error")
            abort(403)

        new_date = request.form.get("new_date", "").strip()
        is_valid_date, err_or_date = validate_booking_date_str(new_date)
        if not is_valid_date:
            flash(err_or_date, "error")
            return redirect(url_for("customer_bookings"))
            
        # State Machine Validation
        if booking["status"] not in {"Pending", "Approved"}:
            flash(f"Booking #{booking_id} cannot be rescheduled because its current status is '{booking['status']}'.", "error")
            return redirect(url_for("customer_bookings"))
            
        if booking["booking_date"] == err_or_date:
            flash("Booking is already scheduled for that date.", "info")
            return redirect(url_for("customer_bookings"))
            
        conn.execute("BEGIN IMMEDIATE")
        conflict = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_date=? AND id!=? AND status NOT IN ('Declined', 'Cancelled') LIMIT 1",
            (err_or_date, booking_id)
        ).fetchone()
        if conflict:
            conn.rollback()
            flash(f"The date {err_or_date} is already reserved by another customer.", "error")
            return redirect(url_for("customer_bookings"))
            
        conn.execute("UPDATE bookings SET booking_date=? WHERE id=?", (err_or_date, booking_id))
        queue_notification(conn, customer["email"], "email", "Booking Rescheduled", f"Your booking #{booking_id} has been rescheduled to {err_or_date}.")
        conn.commit()
        flash(f"Booking #{booking_id} has been rescheduled to {err_or_date} successfully.", "success")
    except (sqlite3.IntegrityError, sqlite3.OperationalError):
        conn.rollback()
        flash(f"The date {err_or_date} was concurrently reserved by another customer.", "error")
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        flash("An error occurred while rescheduling your booking.", "error")
    finally:
        conn.close()
        
    return redirect(url_for("customer_bookings"))



@app.route("/payment/<kind>/<int:record_id>")
def payment(kind, record_id):
    _, record, amount = payment_record(kind, record_id); return render_template("payment.html", kind=kind, record=record, amount=amount, upi_id=UPI_ID)

@app.route("/payment/<kind>/<int:record_id>/qr")
def payment_qr(kind, record_id):
    _, _, amount = payment_record(kind, record_id)
    payload = "upi://pay?" + urlencode({"pa":UPI_ID,"pn":"AK CLICKS","am":amount,"cu":"INR","tn":f"AK{kind[:1].upper()}{record_id}"})
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2); output = io.BytesIO(); image.save(output)
    return Response(output.getvalue(), mimetype="image/svg+xml")

@app.route("/payment/<kind>/<int:record_id>/confirm", methods=["POST"])
def confirm_payment(kind, record_id):
    table, record, _ = payment_record(kind, record_id); method = request.form.get("method")
    if method not in {"upi","netbanking","card"}: flash("Choose a payment method.", "error"); return redirect(url_for("payment", kind=kind, record_id=record_id))
    email = record["email"]
    with db_connection() as conn:
        conn.execute(f"UPDATE {table} SET payment_status='Payment submitted (test)',payment_method=? WHERE id=?", (method, record_id))
        queue_notification(conn, email, "whatsapp", "Payment submitted", f"Payment submission received for {kind} #{record_id}. This is test mode.")
    return render_template("confirmation.html", kind=kind, record_id=record_id, paid=True, year=datetime.now().year)

@app.route("/receipt/<kind>/<int:record_id>.pdf")
def receipt(kind, record_id):
    if kind != "booking":
        abort(404)
    table, record, amount = payment_record(kind, record_id)
    
    # Ownership & Admin authorization check
    is_admin = session.get("admin")
    is_owner = False
    customer_id = session.get("customer_id")
    if customer_id:
        with db_connection() as conn:
            cust = conn.execute("SELECT email FROM customers WHERE id=?", (customer_id,)).fetchone()
            if cust and cust["email"].lower() == record["email"].lower():
                is_owner = True
    if not (is_admin or is_owner):
        abort(403)

    data = io.BytesIO(); pdf = canvas.Canvas(data, pagesize=A4); width, height = A4
    pdf.setFillColor("#1d1b18"); pdf.rect(0, height-52*mm, width, 52*mm, fill=1, stroke=0); pdf.setFillColor("white"); pdf.setFont("Helvetica-Bold", 22); pdf.drawString(22*mm, height-28*mm, "AK CLICKS"); pdf.setFont("Helvetica", 10); pdf.drawString(22*mm, height-36*mm, "Payment receipt - test mode")
    pdf.setFillColor("#1d1b18"); pdf.setFont("Helvetica-Bold", 18); pdf.drawString(22*mm, height-75*mm, "Receipt")
    lines = [("Reference", f"{kind.upper()}-{record_id}"),("Customer", record["name"] if kind == "booking" else record["customer_name"]),("Email", record["email"]),("Item", record["service"] if kind == "booking" else record["items"]),("Amount", f"INR {amount:,.0f}"),("Payment", record["payment_status"])]
    y = height-95*mm; pdf.setFont("Helvetica", 11)
    for label, value in lines: pdf.setFont("Helvetica-Bold", 10); pdf.drawString(22*mm,y,label); pdf.setFont("Helvetica",10); pdf.drawString(65*mm,y,str(value)[:90]); y -= 11*mm
    pdf.setFillColor("#6c665f"); pdf.setFont("Helvetica", 9); pdf.drawString(22*mm, 25*mm, "This receipt is generated in test mode and is not proof of a financial transaction."); pdf.save()
    return Response(data.getvalue(), mimetype="application/pdf", headers={"Content-Disposition":f"attachment; filename=receipt-{kind}-{record_id}.pdf"})

@app.route("/account", methods=["GET","POST"])
def account():
    if session.get("customer_id"):
        return redirect(url_for("customer_home"))
    if request.method == "GET":
        return redirect(url_for("customer_login"))

    action = request.form.get("action")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    destination = "customer_signup" if action == "register" else "customer_login"
    with db_connection() as conn:
        if action == "register":
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            confirm_password = request.form.get("confirm_password", "")
            if not name or not email or not phone or len(password) < 6:
                flash("Complete every field and use a password with at least 6 characters.", "error")
            elif password != confirm_password:
                flash("Password and confirmation do not match.", "error")
            elif conn.execute("SELECT 1 FROM customers WHERE email=?", (email,)).fetchone():
                flash("An account already uses this email.", "error")
            else:
                verification_token = secrets.token_urlsafe(32)
                cursor = conn.execute(
                    "INSERT INTO customers (name,email,phone,password_hash,is_verified,verification_token) VALUES (?,?,?,?,?,?)",
                    (name, email, phone, generate_password_hash(password), 1, verification_token),
                )
                session["customer_id"] = cursor.lastrowid
                session["customer_name"] = name
                flash("Account created successfully! Welcome to AK CLICKS.", "success")
                return redirect(url_for("customer_home"))
        elif action == "login":
            customer = conn.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
            if customer and check_password_hash(customer["password_hash"], password):
                session["customer_id"] = customer["id"]
                session["customer_name"] = customer["name"]
                return redirect(url_for("customer_home"))
            flash("Invalid email or password.", "error")
        else:
            flash("Please use the login or sign-up form.", "error")
    return redirect(url_for(destination))

@app.route("/customer/login", methods=["GET", "POST"])
@app.route("/customer-login", methods=["GET", "POST"])
@app.route("/account/login", methods=["GET", "POST"])
def customer_login():
    if session.get("customer_id"):
        return redirect(url_for("customer_home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db_connection() as conn:
            customer = conn.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
            if customer and check_password_hash(customer["password_hash"], password):
                session["customer_id"] = customer["id"]
                session["customer_name"] = customer["name"]
                flash(f"Welcome back, {customer['name']}!", "success")
                return redirect(url_for("customer_home"))
            flash("Invalid email or password.", "error")

    return render_template("login.html")

@app.route("/customer/signup", methods=["GET", "POST"])
@app.route("/customer-signup", methods=["GET", "POST"])
@app.route("/account/signup", methods=["GET", "POST"])
def customer_signup():
    if session.get("customer_id"):
        return redirect(url_for("customer_home"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", password)

        if not name or not email or not phone or len(password) < 6:
            flash("Complete every field and use a password with at least 6 characters.", "error")
        elif password != confirm_password:
            flash("Password and confirmation do not match.", "error")
        else:
            with db_connection() as conn:
                if conn.execute("SELECT 1 FROM customers WHERE email=?", (email,)).fetchone():
                    flash("An account already uses this email.", "error")
                else:
                    verification_token = secrets.token_urlsafe(32)
                    cursor = conn.execute(
                        "INSERT INTO customers (name,email,phone,password_hash,is_verified,verification_token) VALUES (?,?,?,?,?,?)",
                        (name, email, phone, generate_password_hash(password), 1, verification_token),
                    )
                    session["customer_id"] = cursor.lastrowid
                    session["customer_name"] = name
                    flash("Account created successfully! Welcome to AK CLICKS.", "success")
                    return redirect(url_for("customer_home"))

    return render_template("signup.html")

@app.route("/customer/logout")
@app.route("/account/logout")
def customer_logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    session.pop("user_id", None)
    flash("You have been logged out of Photography Booking.", "info")
    return redirect(url_for("home"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        with db_connection() as conn:
            customer = conn.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
            if customer:
                reset_token = secrets.token_urlsafe(32)
                expiry = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE customers SET reset_token=?, reset_token_expiry=? WHERE id=?",
                    (reset_token, expiry, customer["id"]),
                )
                print("Reset Token Generated", flush=True)
                reset_url = url_for("reset_password", token=reset_token, _external=True)
                subject = "AK CLICKS Password Reset"
                body = f"Hello {customer['name']},\n\nWe received a request to reset your password.\n\nClick the secure link below to reset your password.\n\n{reset_url}\n\nThis link expires in 30 minutes.\n\nIf you didn't request this, simply ignore this email.\n\nRegards,\nAK CLICKS"
                queue_notification(conn, email, "email", subject, body)
                success, error_msg = send_email_with_logs(email, subject, body)
                if success:
                    flash("Password reset email sent successfully.", "success")
                else:
                    flash(f"Failed to send password reset email. SMTP Error: {error_msg}", "error")
            else:
                flash("If an account with that email exists, password reset instructions have been sent.", "info")
        return redirect(url_for("forgot_password"))
    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    with db_connection() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE reset_token=?", (token,)).fetchone()
        if not customer or not customer["reset_token_expiry"]:
            flash("Invalid or expired reset link.", "error")
            return redirect(url_for("forgot_password"))

        try:
            expiry = datetime.strptime(customer["reset_token_expiry"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            flash("Invalid or expired reset link.", "error")
            return redirect(url_for("forgot_password"))

        if datetime.now() > expiry:
            flash("This reset token has expired. Please request a new one.", "error")
            return redirect(url_for("forgot_password"))

        if request.method == "POST":
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if len(new_password) < 8:
                flash("Password must be at least 8 characters long.", "error")
                return render_template("reset_password.html", token=token)

            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
                return render_template("reset_password.html", token=token)

            conn.execute(
                "UPDATE customers SET password_hash=?, reset_token=NULL, reset_token_expiry=NULL WHERE id=?",
                (generate_password_hash(new_password), customer["id"]),
            )
            flash("Password updated successfully. Please log in with your new password.", "success")
            return redirect(url_for("customer_login"))

    return render_template("reset_password.html", token=token)

@app.route("/verify-email/<token>")
def verify_email(token):
    with db_connection() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE verification_token=?", (token,)).fetchone()
        if not customer:
            flash("Invalid or expired verification token.", "error")
            return redirect(url_for("customer_login"))

        conn.execute(
            "UPDATE customers SET is_verified=1, verification_token=NULL WHERE id=?",
            (customer["id"],),
        )
    return render_template("verify_email_success.html")

@app.route("/customer")
def customer_home():
    if not session.get("customer_id"):
        return redirect(url_for("account"))

    with db_connection() as conn:
        customer = conn.execute(
            "SELECT * FROM customers WHERE id=?",
            (session["customer_id"],)
        ).fetchone()

        if not customer:
            customer = {"name": session.get("customer_name", "Customer"), "email": session.get("customer_email", "")}

        email = customer["email"]

        bookings = conn.execute(
            "SELECT * FROM bookings WHERE email=? ORDER BY id DESC",
            (email,)
        ).fetchall()

        # This is dashboard-only, read-only data.  A customer can see the next
        # pending or approved session, while completed and declined records are
        # deliberately excluded from the upcoming-session card.
        upcoming_booking = conn.execute(
            """
            SELECT *
            FROM bookings
            WHERE email = ?
                AND booking_date >= ?
                AND status NOT IN ('Declined', 'Completed', 'Cancelled')
            ORDER BY booking_date ASC, id ASC
            LIMIT 1
            """,
            (email, date.today().isoformat())
        ).fetchone()

        unread_notifications = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE recipient=? AND is_read=0",
            (email,)
        ).fetchone()[0]

    def activity_time(value):
        """Make SQLite timestamps useful to the dashboard without altering data."""
        if not value:
            return "Date unavailable", "Recently"
        try:
            occurred_at = datetime.fromisoformat(str(value))
            elapsed = max(datetime.now() - occurred_at, timedelta(0))
            seconds = int(elapsed.total_seconds())
            if seconds < 60:
                relative = "Just now"
            elif seconds < 3600:
                relative = f"{seconds // 60} min ago"
            elif seconds < 86400:
                relative = f"{seconds // 3600} hr ago"
            elif seconds < 604800:
                relative = f"{seconds // 86400} days ago"
            else:
                relative = occurred_at.strftime("%d %b %Y")
            return occurred_at.strftime("%d %b %Y, %I:%M %p"), relative
        except (TypeError, ValueError):
            return str(value), "Previously"

    def dashboard_value(row, column, default=None):
        """Read legacy SQLite rows safely when an optional column is absent."""
        return row[column] if column in row.keys() else default

    # Booking activities are calculated from the existing booking records.  No
    # new table or status history is required, so all current workflows remain
    # untouched.
    booking_timeline = []
    status_activity = {
        "Pending": ("Booking awaiting approval", "fa-hourglass-half", "pending"),
        "Approved": ("Booking approved", "fa-circle-check", "approved"),
        "Completed": ("Event completed", "fa-camera-retro", "completed"),
        "Declined": ("Booking declined", "fa-circle-xmark", "declined"),
        "Cancelled": ("Booking cancelled", "fa-ban", "declined"),
    }
    for booking in bookings:
        created_at = dashboard_value(booking, "created_at")
        display_time, relative_time = activity_time(created_at)
        service = booking["service"] or "Photography booking"
        booking_timeline.append({
            "title": "Booking created",
            "detail": service,
            "timestamp": display_time,
            "relative_time": relative_time,
            "icon": "fa-calendar-plus",
            "tone": "created",
            "sort_time": str(created_at or ""),
        })
        payment_status = (dashboard_value(booking, "payment_status", "") or "").lower()
        if payment_status and payment_status != "unpaid":
            payment_title = "Payment completed" if payment_status == "paid" else "Payment submitted"
            booking_timeline.append({
                "title": payment_title,
                "detail": service,
                "timestamp": display_time,
                "relative_time": relative_time,
                "icon": "fa-credit-card",
                "tone": "paid",
                "sort_time": str(created_at or ""),
            })
        title, icon, tone = status_activity.get(
            booking["status"], ("Booking updated", "fa-pen-to-square", "created")
        )
        booking_timeline.append({
            "title": title,
            "detail": service,
            "timestamp": display_time,
            "relative_time": relative_time,
            "icon": icon,
            "tone": tone,
            "sort_time": str(created_at or ""),
        })
    booking_timeline.sort(key=lambda item: item["sort_time"], reverse=True)

    # Chart values are derived in memory from the customer's existing rows.
    # The dashboard only reads data; it does not create or update any record.
    status_counts = Counter((booking["status"] or "Pending") for booking in bookings)
    month_keys = []
    month_labels = []
    current_year, current_month = date.today().year, date.today().month
    for offset in range(5, -1, -1):
        month = current_month - offset
        year = current_year
        while month <= 0:
            month += 12
            year -= 1
        month_keys.append(f"{year:04d}-{month:02d}")
        month_labels.append(date(year, month, 1).strftime("%b"))

    dashboard_charts = {
        "booking_status": {
            "labels": list(status_counts.keys()),
            "values": list(status_counts.values()),
        },
        "monthly_bookings": {
            "labels": month_labels,
            "values": [sum(str(booking["booking_date"] or "").startswith(key) for booking in bookings) for key in month_keys],
        },
        "approval_progress": {
            "labels": ["Approved", "Pending"],
            "values": [status_counts.get("Approved", 0), status_counts.get("Pending", 0)],
        },
    }

    return render_template(
        "customer_home.html",
        customer=customer,
        bookings=bookings,
        unread_notifications=unread_notifications,
        upcoming_booking=upcoming_booking,
        booking_timeline=booking_timeline[:8],
        dashboard_charts=dashboard_charts,
    )

@app.route("/customer/profile")
def customer_profile():
    if not session.get("customer_id"):
        return redirect(url_for("account"))

    with db_connection() as conn:
        customer = conn.execute(
            "SELECT * FROM customers WHERE id=?",
            (session["customer_id"],)
        ).fetchone()

    return render_template(
        "customer_profile.html",
        customer=customer
    )

@app.route("/customer/profile/edit", methods=["GET", "POST"])
def edit_profile():
    if not session.get("customer_id"):
        return redirect(url_for("account"))

    with db_connection() as conn:

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()

            if not name or not email:
                flash("Name and email are required.", "error")
                return redirect(url_for("edit_profile"))

            duplicate = conn.execute(
                "SELECT 1 FROM customers WHERE email=? AND id != ?",
                (email, session["customer_id"]),
            ).fetchone()
            if duplicate:
                flash("Another account already uses this email.", "error")
                return redirect(url_for("edit_profile"))

            conn.execute(
                """
                UPDATE customers
                SET name=?, email=?
                WHERE id=?
                """,
                (name, email, session["customer_id"])
            )

            session["customer_name"] = name

            flash("Profile updated successfully.", "success")

            return redirect(url_for("customer_profile"))

        customer = conn.execute(
            "SELECT * FROM customers WHERE id=?",
            (session["customer_id"],)
        ).fetchone()

    return render_template(
        "edit_profile.html",
        customer=customer
    )

@app.route("/customer/change-password", methods=["GET", "POST"])
def change_password():

    if not session.get("customer_id"):
        return redirect(url_for("account"))

    if request.method == "POST":

        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        with db_connection() as conn:

            customer = conn.execute(
                "SELECT * FROM customers WHERE id=?",
                (session["customer_id"],)
            ).fetchone()

            if not check_password_hash(customer["password_hash"], current_password):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("change_password"))

            if len(new_password or "") < 6:
                flash("New password must contain at least 6 characters.", "error")
                return redirect(url_for("change_password"))

            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
                return redirect(url_for("change_password"))

            conn.execute(
                """
                UPDATE customers
                SET password_hash=?
                WHERE id=?
                """,
                (
                    generate_password_hash(new_password),
                    session["customer_id"]
                )
            )

        flash("Password changed successfully.", "success")

        return redirect(url_for("customer_profile"))

    return render_template("change_password.html")

@app.route("/customer/bookings")
def customer_bookings():

    if not session.get("customer_id"):
        return redirect(url_for("account"))

    with db_connection() as conn:

        customer = conn.execute(
            "SELECT * FROM customers WHERE id=?",
            (session["customer_id"],)
        ).fetchone()

        bookings = conn.execute(
            """
            SELECT *
            FROM bookings
            WHERE email=?
            ORDER BY booking_date DESC
            """,
            (customer["email"],)
        ).fetchall()

    return render_template(
        "customer_bookings.html",
        bookings=bookings
    )

@app.route("/customer/notifications")
def customer_notifications():

    if not session.get("customer_id"):
        return redirect(url_for("account"))

    with db_connection() as conn:

        customer = conn.execute(
            "SELECT * FROM customers WHERE id=?",
            (session["customer_id"],)
        ).fetchone()

        notifications = conn.execute(
            """
            SELECT *
            FROM notifications
            WHERE recipient=?
            ORDER BY id DESC
            """,
            (customer["email"],)
        ).fetchall()

    return render_template(
        "customer_notifications.html",
        notifications=notifications,
        unread_count=sum(1 for notification in notifications if not notification["is_read"])
    )

@app.route("/customer/notifications/<int:notification_id>/read", methods=["POST"])
def update_customer_notification(notification_id):
    if not session.get("customer_id"):
        return redirect(url_for("account"))
    action = request.form.get("action")
    if action not in {"read", "unread"}:
        return redirect(url_for("customer_notifications"))
    with db_connection() as conn:
        customer = conn.execute("SELECT email FROM customers WHERE id=?", (session["customer_id"],)).fetchone()
        if customer:
            conn.execute(
                "UPDATE notifications SET is_read=? WHERE id=? AND recipient=?",
                (1 if action == "read" else 0, notification_id, customer["email"]),
            )
    return redirect(url_for("customer_notifications"))

@app.route("/customer/notifications/<int:notification_id>/delete", methods=["POST"])
def delete_customer_notification(notification_id):
    if not session.get("customer_id"):
        return redirect(url_for("account"))
    with db_connection() as conn:
        customer = conn.execute("SELECT email FROM customers WHERE id=?", (session["customer_id"],)).fetchone()
        if customer:
            conn.execute("DELETE FROM notifications WHERE id=? AND recipient=?", (notification_id, customer["email"]))
    return redirect(url_for("customer_notifications"))

@app.route("/customer/notifications/read-all", methods=["POST"])
def read_all_customer_notifications():
    if not session.get("customer_id"):
        return redirect(url_for("account"))
    with db_connection() as conn:
        customer = conn.execute("SELECT email FROM customers WHERE id=?", (session["customer_id"],)).fetchone()
        if customer:
            conn.execute("UPDATE notifications SET is_read=1 WHERE recipient=?", (customer["email"],))
    return redirect(url_for("customer_notifications"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form.get("username")==os.environ.get("ADMIN_USERNAME","admin") and request.form.get("password")==os.environ.get("ADMIN_PASSWORD","1234"): session["admin"]=True;return redirect(url_for("admin"))
        flash("Invalid username or password.","error")
    return render_template("admin.html")

@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

    with db_connection() as conn:
        total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        total_bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        approved_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='Approved'").fetchone()[0]

        bookings = conn.execute("SELECT * FROM bookings ORDER BY id DESC").fetchall()
        notifications = conn.execute(
            "SELECT * FROM notifications ORDER BY id DESC LIMIT 50"
        ).fetchall()

    calendar_events = [
        {
            "id": booking["id"], "date": booking["booking_date"], "status": booking["status"],
            "name": booking["name"], "email": booking["email"], "phone": booking["phone"],
            "service": booking["service"], "location": booking["location"] or "TBC",
            "payment_status": booking["payment_status"],
        }
        for booking in bookings
    ]

    return render_template(
        "dashboard.html",
        total_customers=total_customers,
        total_bookings=total_bookings,
        approved_bookings=approved_bookings,
        bookings=bookings,
        calendar_events=calendar_events,
        notifications=notifications
    )

# ==============================================================================
# PHOTOGRAPHY ADMIN - CUSTOMER MANAGEMENT & REPORTS MODULES
# ==============================================================================

@app.route("/admin/customers")
def admin_customers():
    if not session.get("admin"):
        return redirect(url_for("login"))

    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")

    with db_connection() as conn:
        if search_query:
            raw_customers = conn.execute(
                "SELECT * FROM customers WHERE name LIKE ? OR email LIKE ? OR phone LIKE ? ORDER BY id DESC",
                (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
            ).fetchall()
        else:
            raw_customers = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()

        customers = []
        for c in raw_customers:
            c_dict = dict(c)
            email = c_dict.get("email", "")

            # Calculate customer aggregate booking metrics
            booking_stats = conn.execute("""
                SELECT 
                    COUNT(*) as total_bookings,
                    MAX(booking_date) as last_booking
                FROM bookings WHERE email=?
            """, (email,)).fetchone()

            c_dict["total_bookings"] = booking_stats["total_bookings"] if booking_stats else 0
            c_dict["last_booking"] = booking_stats["last_booking"] if (booking_stats and booking_stats["last_booking"]) else "N/A"
            c_dict["amount_paid"] = c_dict["total_bookings"] * BOOKING_DEPOSIT
            c_dict["status"] = "Active" if c_dict["total_bookings"] > 0 else "New Lead"

            if status_filter and c_dict["status"].lower() != status_filter.lower():
                continue
            customers.append(c_dict)

    return render_template("admin_customers.html", customers=customers, search_query=search_query)

@app.route("/admin/customer/<int:customer_id>")
def admin_customer_details(customer_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    with db_connection() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            flash("Customer not found.", "error")
            return redirect(url_for("admin_customers"))

        customer = dict(customer)
        bookings = [dict(r) for r in conn.execute(
            "SELECT * FROM bookings WHERE email=? ORDER BY id DESC", (customer["email"],)
        ).fetchall()]

        total_bookings = len(bookings)
        approved_bookings = sum(1 for b in bookings if b["status"] == "Approved")
        completed_bookings = sum(1 for b in bookings if b["status"] == "Completed")
        total_spent = total_bookings * BOOKING_DEPOSIT

    return render_template(
        "admin_customer_details.html",
        customer=customer,
        bookings=bookings,
        total_bookings=total_bookings,
        approved_bookings=approved_bookings,
        completed_bookings=completed_bookings,
        total_spent=total_spent
    )

@app.route("/admin/customer/edit/<int:customer_id>", methods=["GET", "POST"])
def admin_customer_edit(customer_id):
    if not session.get("admin"):
        abort(403)

    with db_connection() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            flash("Customer not found.", "error")
            return redirect(url_for("admin_customers"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone", "").strip()

            if not name or not email:
                flash("Name and Email are required.", "error")
            else:
                conn.execute("UPDATE customers SET name=?, email=?, phone=? WHERE id=?", (name, email, phone, customer_id))
                flash("Customer profile updated successfully.", "success")
                return redirect(url_for("admin_customer_details", customer_id=customer_id))

    return render_template("admin_customer_details.html", customer=dict(customer), bookings=[])

@app.route("/admin/customer/delete/<int:customer_id>", methods=["POST"])
def admin_customer_delete(customer_id):
    if not session.get("admin"):
        abort(403)

    with db_connection() as conn:
        conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
        flash("Customer record deleted successfully.", "success")

    return redirect(url_for("admin_customers"))

@app.route("/admin/customers/export")
def admin_customers_export():
    if not session.get("admin"):
        return redirect(url_for("login"))

    with db_connection() as conn:
        customers = conn.execute("SELECT id, name, email, phone, created_at FROM customers ORDER BY id DESC").fetchall()

    output = io.StringIO()
    output.write("Customer ID,Name,Email,Phone,Joined Date\n")
    for c in customers:
        output.write(f'"{c["id"]}","{c["name"]}","{c["email"]}","{c["phone"]}","{c["created_at"]}"\n')

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=photography_customers.csv"}
    )

@app.route("/admin/reports")
def admin_reports():
    if not session.get("admin"):
        return redirect(url_for("login"))

    range_filter = request.args.get("range", "this_month")

    with db_connection() as conn:
        total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        total_bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        
        today_str = date.today().isoformat()
        today_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE booking_date=?", (today_str,)).fetchone()[0]
        
        monthly_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE booking_date >= date('now', 'start of month')").fetchone()[0]
        completed_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='Completed'").fetchone()[0]
        cancelled_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='Declined' OR status='Cancelled'").fetchone()[0]
        
        approved_count = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='Approved'").fetchone()[0]
        pending_count = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='Pending'").fetchone()[0]

        total_revenue = total_bookings * BOOKING_DEPOSIT
        pending_payments = pending_count * BOOKING_DEPOSIT

        latest_bookings = [dict(r) for r in conn.execute("SELECT * FROM bookings ORDER BY id DESC LIMIT 10").fetchall()]
        top_customers = [dict(r) for r in conn.execute(
            "SELECT c.*, COUNT(b.id) as booking_count FROM customers c LEFT JOIN bookings b ON c.email=b.email GROUP BY c.id ORDER BY booking_count DESC LIMIT 5"
        ).fetchall()]

        pkg_rows = conn.execute("SELECT service, COUNT(*) as cnt FROM bookings GROUP BY service").fetchall()
        package_stats = {r["service"]: r["cnt"] for r in pkg_rows}

    return render_template(
        "admin_reports.html",
        total_customers=total_customers,
        total_bookings=total_bookings,
        today_bookings=today_bookings,
        monthly_bookings=monthly_bookings,
        completed_bookings=completed_bookings,
        cancelled_bookings=cancelled_bookings,
        approved_count=approved_count,
        pending_count=pending_count,
        total_revenue=total_revenue,
        pending_payments=pending_payments,
        latest_bookings=latest_bookings,
        top_customers=top_customers,
        package_stats=package_stats,
        range_filter=range_filter
    )

@app.route("/admin/reports/download/pdf")
def admin_reports_download_pdf():
    if not session.get("admin"):
        return redirect(url_for("login"))

    with db_connection() as conn:
        total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        total_bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        total_revenue = total_bookings * BOOKING_DEPOSIT
        bookings = conn.execute("SELECT * FROM bookings ORDER BY id DESC LIMIT 20").fetchall()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("AK CLICKS Photography Business Report")

    # Title Header
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(40, 800, "AK CLICKS Studio - Executive Business Report")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, 785, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Summary Cards
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, 750, "Business Summary Metrics:")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, 730, f"Total Customers Registered: {total_customers}")
    pdf.drawString(50, 715, f"Total Photography Bookings: {total_bookings}")
    pdf.drawString(50, 700, f"Total Revenue Generated: Rs. {total_revenue:,} INR")

    # Bookings Table Header
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, 665, "Recent Photography Bookings:")
    
    y = 645
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "ID")
    pdf.drawString(70, y, "Customer Name")
    pdf.drawString(200, y, "Service")
    pdf.drawString(340, y, "Date")
    pdf.drawString(440, y, "Status")

    pdf.setFont("Helvetica", 9)
    for b in bookings:
        y -= 20
        if y < 50:
            pdf.showPage()
            y = 780
        pdf.drawString(40, y, str(b["id"]))
        pdf.drawString(70, y, str(b["name"])[:20])
        pdf.drawString(200, y, str(b["service"])[:22])
        pdf.drawString(340, y, str(b["booking_date"]))
        pdf.drawString(440, y, str(b["status"]))

    pdf.save()
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="photography_business_report.pdf",
        mimetype="application/pdf"
    )

@app.route("/admin/reports/download/excel")
def admin_reports_download_excel():
    if not session.get("admin"):
        return redirect(url_for("login"))

    with db_connection() as conn:
        bookings = conn.execute("SELECT id, name, email, phone, service, booking_date, location, status FROM bookings ORDER BY id DESC").fetchall()

    output = io.StringIO()
    output.write("Booking ID,Customer Name,Email,Phone,Service,Booking Date,Location,Status,Deposit Paid\n")
    for b in bookings:
        output.write(f'"{b["id"]}","{b["name"]}","{b["email"]}","{b["phone"]}","{b["service"]}","{b["booking_date"]}","{b["location"]}","{b["status"]}","{BOOKING_DEPOSIT}"\n')

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=photography_bookings_report.csv"}
    )



@app.route("/booking/<int:booking_id>/status",methods=["POST"])
def update_booking(booking_id):
    if not session.get("admin"): abort(403)
    new_status = request.form.get("status")
    conn = db_connection()
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if booking:
            current_status = booking["status"]
            if not is_valid_status_transition(current_status, new_status):
                flash(f"Invalid status transition from '{current_status}' to '{new_status}'.", "error")
                return redirect(url_for("admin"))
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE bookings SET status=? WHERE id=?", (new_status, booking_id))
            queue_notification(conn, booking["email"], "email", "Booking status updated", f"Your {booking['service']} booking #{booking_id} is now {new_status}.")
            conn.commit()
            flash(f"Booking #{booking_id} status updated to {new_status}.", "success")
    except Exception:
        conn.rollback()
        flash("Failed to update booking status.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin"))

@app.route("/booking/<int:booking_id>/edit", methods=["POST"])
def edit_booking(booking_id):
    if not session.get("admin"):
        abort(403)
    fields = {key: request.form.get(key, "").strip() for key in ("name", "email", "phone", "service", "booking_date", "location", "payment_status")}
    if not all(fields[key] for key in ("name", "email", "phone", "service", "booking_date")):
        flash("Booking details require a name, email, phone, service, and date.", "error")
        return redirect(url_for("admin"))
        
    is_valid_date, date_res = validate_booking_date_str(fields["booking_date"], allow_past=True)
    if not is_valid_date:
        flash(date_res, "error")
        return redirect(url_for("admin"))
        
    conn = db_connection()
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if booking is None:
            conn.close()
            abort(404)
            
        conn.execute("BEGIN IMMEDIATE")
        conflict = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_date=? AND id!=? AND status NOT IN ('Declined', 'Cancelled') LIMIT 1",
            (date_res, booking_id),
        ).fetchone()
        if conflict:
            conn.rollback()
            flash("Another active booking already uses that date.", "error")
            return redirect(url_for("admin"))
            
        conn.execute(
            "UPDATE bookings SET name=?, email=?, phone=?, service=?, booking_date=?, location=?, payment_status=? WHERE id=?",
            (fields["name"], fields["email"].lower(), fields["phone"], fields["service"], date_res, fields["location"], fields["payment_status"], booking_id),
        )
        queue_notification(conn, fields["email"].lower(), "email", "Booking details updated", f"Your {fields['service']} booking #{booking_id} was updated by AK CLICKS.")
        conn.commit()
        flash("Booking details updated successfully.", "success")
    except (sqlite3.IntegrityError, sqlite3.OperationalError):
        conn.rollback()
        flash("Date conflict error: another active booking occupies that date.", "error")
    except Exception:
        conn.rollback()
        flash("Error updating booking details.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin"))

@app.route("/logout")
def logout(): session.clear();return redirect(url_for("login"))

@app.route("/admin/booking/edit/<int:booking_id>", methods=["GET", "POST"])
def admin_edit_booking(booking_id):
    if not session.get("admin"):
        abort(403)
    conn = db_connection()
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            conn.close()
            abort(404)
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone", "").strip()
            service = request.form.get("service", "").strip()
            booking_date = request.form.get("booking_date", "").strip()
            location = request.form.get("location", "").strip()
            status = request.form.get("status", "").strip()
            if not all([name, email, phone, service, booking_date, status]):
                flash("Client Name, Email, Phone, Service, Date, and Status are required.", "error")
                return render_template("edit_booking.html", booking=booking)
            
            is_valid_date, date_res = validate_booking_date_str(booking_date, allow_past=True)
            if not is_valid_date:
                flash(date_res, "error")
                return render_template("edit_booking.html", booking=booking)
                
            if not is_valid_status_transition(booking["status"], status):
                flash(f"Invalid status transition from '{booking['status']}' to '{status}'.", "error")
                return render_template("edit_booking.html", booking=booking)
                
            conn.execute("BEGIN IMMEDIATE")
            conflict = conn.execute(
                "SELECT 1 FROM bookings WHERE booking_date=? AND id!=? AND status NOT IN ('Declined', 'Cancelled') LIMIT 1",
                (date_res, booking_id),
            ).fetchone()
            if conflict:
                conn.rollback()
                flash("Another active booking already occupies that date.", "error")
                return render_template("edit_booking.html", booking=booking)
                
            conn.execute(
                "UPDATE bookings SET name=?, email=?, phone=?, service=?, booking_date=?, location=?, status=? WHERE id=?",
                (name, email, phone, service, date_res, location, status, booking_id)
            )
            conn.commit()
            flash("Booking updated successfully.", "success")
            return redirect(url_for("admin") + "#bookings")
    except (sqlite3.IntegrityError, sqlite3.OperationalError):
        conn.rollback()
        flash("Date conflict error: another active booking occupies that date.", "error")
    finally:
        conn.close()
    return render_template("edit_booking.html", booking=booking)

@app.route("/admin/booking/delete/<int:booking_id>", methods=["POST"])
def admin_delete_booking(booking_id):
    if not session.get("admin"):
        abort(403)
    with db_connection() as conn:
        conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    flash("Booking deleted successfully.", "success")
    return redirect(url_for("admin") + "#bookings")



# ================= Standalone Story Store Helper & Routes =================


# Initialize database
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
