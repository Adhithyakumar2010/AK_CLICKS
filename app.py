import io
import os
import secrets
import sqlite3
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

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-before-production")
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() in ("true", "1", "on")
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "false").lower() in ("true", "1", "on")
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get("MAIL_USERNAME") or "noreply@akclicks.com"

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

def db_connection():
    conn = sqlite3.connect("bookings.db")
    conn.row_factory = sqlite3.Row
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
def add_favicon_to_html_pages(response):
    """Keep favicon markup identical across every independently-rendered template."""
    if response.mimetype == "text/html":
        page = response.get_data(as_text=True)
        if "</head>" in page and "images/favicon.ico" not in page:
            response.set_data(page.replace("</head>", favicon_head_markup() + "</head>", 1))
    return response

def add_column_if_missing(conn, table, column, definition):
    if column not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def queue_notification(conn, recipient, channel, subject, body):
    conn.execute("INSERT INTO notifications (recipient, channel, subject, body) VALUES (?, ?, ?, ?)", (recipient, channel, subject, body))

def init_db():
    with db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,service TEXT NOT NULL,booking_date TEXT NOT NULL,location TEXT,message TEXT,status TEXT NOT NULL DEFAULT 'Pending',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT,customer_name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,address TEXT NOT NULL,items TEXT NOT NULL,total INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'New',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,price INTEGER NOT NULL,image TEXT NOT NULL,description TEXT NOT NULL,stock INTEGER NOT NULL DEFAULT 10)")
        conn.execute("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT,recipient TEXT NOT NULL,channel TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Queued',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        for table in ("bookings", "orders"):
            add_column_if_missing(conn, table, "payment_status", "TEXT NOT NULL DEFAULT 'Unpaid'")
            add_column_if_missing(conn, table, "payment_method", "TEXT")

        add_column_if_missing(conn, "orders", "customer_id", "INTEGER")

    # NEW
        add_column_if_missing(conn, "customers", "phone", "TEXT")
        add_column_if_missing(conn, "customers", "address", "TEXT")
        add_column_if_missing(conn, "customers", "profile_image", "TEXT DEFAULT 'images/default-profile.png'")
        add_column_if_missing(conn, "customers", "is_verified", "INTEGER DEFAULT 1")
        add_column_if_missing(conn, "customers", "verification_token", "TEXT")
        add_column_if_missing(conn, "customers", "reset_token", "TEXT")
        add_column_if_missing(conn, "customers", "reset_token_expiry", "DATETIME")
        add_column_if_missing(conn, "notifications", "is_read", "INTEGER NOT NULL DEFAULT 0")

        for item in PRODUCTS:
            conn.execute("INSERT OR IGNORE INTO products (id,name,category,price,image,description,stock) VALUES (:id,:name,:category,:price,:image,:description,10)", item)

def catalog_products():
    with db_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY name").fetchall()]

def payment_record(kind, record_id):
    table = "bookings" if kind == "booking" else "orders" if kind == "order" else None
    if not table: abort(404)
    with db_connection() as conn:
        record = conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
    if record is None: abort(404)
    if kind == "booking":
        package = record["service"].rsplit(" — ", 1)[-1]
        return table, record, BOOKING_PACKAGES.get(package, BOOKING_DEPOSIT)
    return table, record, record["total"]

def pending_booking():
    data = session.get("pending_booking")
    required = {"name", "email", "phone", "service", "package", "location"}
    return data if isinstance(data, dict) and required.issubset(data) else None

@app.route("/")
def home(): return render_template("index.html", products=catalog_products(), year=datetime.now().year)

@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="images/favicon.ico", v=FAVICON_VERSION))

@app.route("/availability")
def availability():
    date = request.args.get("date", "")
    with db_connection() as conn:
        statuses = [row["status"] for row in conn.execute("SELECT status FROM bookings WHERE booking_date=? AND status != 'Declined'", (date,)).fetchall()]
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
            "SELECT booking_date, status FROM bookings WHERE booking_date >= ? AND booking_date < ? AND status != 'Declined'",
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
            "SELECT 1 FROM bookings WHERE booking_date=? AND status != 'Declined' LIMIT 1",
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
    details = pending_booking()
    method = request.form.get("method")
    if not details or not details.get("booking_date"):
        flash("Your booking session has expired. Please start again.", "error")
        return redirect(url_for("home") + "#booking")
    if method not in {"upi", "netbanking", "card"}:
        flash("Choose a payment method.", "error")
        return redirect(url_for("pending_booking_payment"))
    with db_connection() as conn:
        unavailable = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_date=? AND status != 'Declined' LIMIT 1",
            (details["booking_date"],),
        ).fetchone()
        if unavailable:
            flash("That date is no longer available. Please choose another date.", "error")
            return redirect(url_for("booking_calendar"))
        service = f"{details['service']} — {details['package']}"
        message = f"Package: {details['package']}\n{details['message']}".strip()
        cursor = conn.execute(
            "INSERT INTO bookings (name,email,phone,service,booking_date,location,message,payment_status,payment_method) VALUES (?,?,?,?,?,?,?,?,?)",
            (details["name"], details["email"], details["phone"], service, details["booking_date"], details["location"], message, "Payment submitted (test)", method),
        )
        booking_id = cursor.lastrowid
        queue_notification(conn, details["email"], "email", "Booking enquiry received", f"Your {service} enquiry is recorded. Booking reference: {booking_id}.")
        queue_notification(conn, details["email"], "whatsapp", "Payment submitted", f"Payment submission received for booking #{booking_id}. This is test mode.")
    session.pop("pending_booking", None)
    return render_template("confirmation.html", kind="booking", record_id=booking_id, paid=True, year=datetime.now().year)

@app.route("/shop")
def shop(): return render_template("shop.html", products=catalog_products(), year=datetime.now().year)

@app.route("/order", methods=["POST"])
def order():
    customer = {key: request.form.get(key, "").strip() for key in ("customer_name","email","phone","address","items")}
    requested = Counter(item.strip() for item in customer["items"].split(",") if item.strip())
    with db_connection() as conn:
        all_products = {row["name"]: row for row in conn.execute("SELECT * FROM products")}
        if not all(customer.values()) or not requested or any(name not in all_products or all_products[name]["stock"] < quantity for name, quantity in requested.items()):
            flash("One or more books are unavailable. Please refresh your bag.", "error"); return redirect(url_for("shop"))
        total = sum(all_products[name]["price"] * quantity for name, quantity in requested.items())
        for name, quantity in requested.items(): conn.execute("UPDATE products SET stock=stock-? WHERE id=?", (quantity, all_products[name]["id"]))
        cursor = conn.execute(
            "INSERT INTO orders (customer_name,email,phone,address,items,total,customer_id) VALUES (?,?,?,?,?,?,?)",
            (
                customer["customer_name"], customer["email"], customer["phone"],
                customer["address"], customer["items"], total, session.get("customer_id")
            ),
        )
        order_id = cursor.lastrowid
        queue_notification(conn, customer["email"], "email", "Story Shop order received", f"Your order #{order_id} totals Rs. {total}.")
    return redirect(url_for("payment", kind="order", record_id=order_id))

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
    _, record, amount = payment_record(kind, record_id); data = io.BytesIO(); pdf = canvas.Canvas(data, pagesize=A4); width, height = A4
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

@app.route("/account/login")
def customer_login():
    if session.get("customer_id"):
        return redirect(url_for("customer_home"))
    return render_template("login.html")

@app.route("/account/signup")
def customer_signup():
    if session.get("customer_id"):
        return redirect(url_for("customer_home"))
    return render_template("signup.html")

@app.route("/account/logout")
def customer_logout(): session.pop("customer_id",None);session.pop("customer_name",None);return redirect(url_for("home"))

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

        orders = conn.execute(
            "SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC",
            (session["customer_id"],)
        ).fetchall()

        bookings = conn.execute(
            "SELECT * FROM bookings WHERE email=? ORDER BY id DESC",
            (customer["email"],)
        ).fetchall()

        upcoming_booking = conn.execute(
            """
            SELECT *
            FROM bookings
            WHERE email = ?
                AND status = 'Approved'
                AND booking_date >= ?
            ORDER BY booking_date ASC
            LIMIT 1
            """,
            (customer["email"], date.today().isoformat())
        ).fetchone()        

        unread_notifications = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE recipient=? AND is_read=0",
            (customer["email"],)
        ).fetchone()[0]

    return render_template(
        "customer_home.html",
        customer=customer,
        orders=orders,
        bookings=bookings,
        unread_notifications=unread_notifications,
        upcoming_booking=upcoming_booking
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

@app.route("/customer/orders")
def customer_orders():
    if not session.get("customer_id"):
        return redirect(url_for("account"))

    with db_connection() as conn:
        orders = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE customer_id=?
            ORDER BY id DESC
            """,
            (session["customer_id"],)
        ).fetchall()

    return render_template(
        "customer_orders.html",
        orders=orders
    )

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

        total_customers = conn.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

        total_bookings = conn.execute(
            "SELECT COUNT(*) FROM bookings"
        ).fetchone()[0]

        total_orders = conn.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(total),0) FROM orders"
        ).fetchone()[0]

        bookings = conn.execute("SELECT * FROM bookings ORDER BY id DESC").fetchall()
        orders = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
        products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
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
        total_orders=total_orders,
        total_revenue=total_revenue,
        bookings=bookings,
        calendar_events=calendar_events,
        orders=orders,
        products=products,
        notifications=notifications
    )

@app.route("/product/<product_id>/stock",methods=["POST"])
def update_stock(product_id):
    if not session.get("admin"): return redirect(url_for("login"))
    try: stock=max(0,int(request.form.get("stock","0")))
    except ValueError: return redirect(url_for("admin"))
    with db_connection() as conn: conn.execute("UPDATE products SET stock=? WHERE id=?",(stock,product_id))
    return redirect(url_for("admin"))

@app.route("/booking/<int:booking_id>/status",methods=["POST"])
def update_booking(booking_id):
    if not session.get("admin"): return redirect(url_for("login"))
    status = request.form.get("status")
    if status in {"Pending", "Approved", "Declined", "Completed"}:
        with db_connection() as conn:
            booking = conn.execute("SELECT email, service FROM bookings WHERE id=?", (booking_id,)).fetchone()
            conn.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
            if booking:
                queue_notification(conn, booking["email"], "email", "Booking status updated", f"Your {booking['service']} booking #{booking_id} is now {status}.")
    return redirect(url_for("admin"))

@app.route("/booking/<int:booking_id>/edit", methods=["POST"])
def edit_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    fields = {key: request.form.get(key, "").strip() for key in ("name", "email", "phone", "service", "booking_date", "location", "payment_status")}
    if not all(fields[key] for key in ("name", "email", "phone", "service", "booking_date")):
        flash("Booking details require a name, email, phone, service, and date.", "error")
        return redirect(url_for("admin"))
    try:
        datetime.strptime(fields["booking_date"], "%Y-%m-%d")
    except ValueError:
        flash("Please enter a valid event date.", "error")
        return redirect(url_for("admin"))
    with db_connection() as conn:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if booking is None:
            abort(404)
        conflict = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_date=? AND id!=? AND status != 'Declined' LIMIT 1",
            (fields["booking_date"], booking_id),
        ).fetchone()
        if conflict:
            flash("Another active booking already uses that date.", "error")
            return redirect(url_for("admin"))
        conn.execute(
            "UPDATE bookings SET name=?, email=?, phone=?, service=?, booking_date=?, location=?, payment_status=? WHERE id=?",
            (fields["name"], fields["email"].lower(), fields["phone"], fields["service"], fields["booking_date"], fields["location"], fields["payment_status"], booking_id),
        )
        queue_notification(conn, fields["email"].lower(), "email", "Booking details updated", f"Your {fields['service']} booking #{booking_id} was updated by AK CLICKS.")
    flash("Booking details updated.", "success")
    return redirect(url_for("admin"))

@app.route("/order/<int:order_id>/status",methods=["POST"])
def update_order(order_id):
    if not session.get("admin"): return redirect(url_for("login"))
    if request.form.get("status") in {"New","Processing","Fulfilled"}:
        with db_connection() as conn: conn.execute("UPDATE orders SET status=? WHERE id=?",(request.form["status"],order_id))
    return redirect(url_for("admin"))

@app.route("/logout")
def logout(): session.clear();return redirect(url_for("login"))

@app.route("/admin/booking/edit/<int:booking_id>", methods=["GET", "POST"])
def admin_edit_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    with db_connection() as conn:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
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
            conn.execute(
                "UPDATE bookings SET name=?, email=?, phone=?, service=?, booking_date=?, location=?, status=? WHERE id=?",
                (name, email, phone, service, booking_date, location, status, booking_id)
            )
            flash("Booking updated successfully.", "success")
            return redirect(url_for("admin") + "#bookings")
    return render_template("edit_booking.html", booking=booking)

@app.route("/admin/booking/delete/<int:booking_id>", methods=["POST"])
def admin_delete_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    with db_connection() as conn:
        conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    flash("Booking deleted successfully.", "success")
    return redirect(url_for("admin") + "#bookings")

@app.route("/admin/order/edit/<int:order_id>", methods=["GET", "POST"])
def admin_edit_order(order_id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    with db_connection() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            abort(404)
        if request.method == "POST":
            customer_name = request.form.get("customer_name", "").strip()
            items = request.form.get("items", "").strip()
            status = request.form.get("status", "").strip()
            try:
                total = int(request.form.get("total", "0").strip())
            except ValueError:
                flash("Total Amount must be a valid number.", "error")
                return render_template("edit_order.html", order=order)
            if not all([customer_name, items, status]) or total < 0:
                flash("Customer Name, Items, Status, and non-negative Total are required.", "error")
                return render_template("edit_order.html", order=order)
            conn.execute(
                "UPDATE orders SET customer_name=?, items=?, total=?, status=? WHERE id=?",
                (customer_name, items, total, status, order_id)
            )
            flash("Order updated successfully.", "success")
            return redirect(url_for("admin") + "#orders")
    return render_template("edit_order.html", order=order)

@app.route("/admin/order/delete/<int:order_id>", methods=["POST"])
def admin_delete_order(order_id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    with db_connection() as conn:
        conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
    flash("Order deleted successfully.", "success")
    return redirect(url_for("admin") + "#orders")

# ================= Standalone Story Store Helper & Routes =================

def get_story_book(book_id):
    str_id = str(book_id).strip()
    with db_connection() as conn:
        prod = conn.execute("SELECT * FROM products WHERE id=?", (str_id,)).fetchone()
        if prod:
            return dict(prod)
        prods = [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY name").fetchall()]
        if str_id.isdigit():
            idx = int(str_id) - 1
            if 0 <= idx < len(prods):
                return prods[idx]
        for p in prods:
            if p["id"].lower() == str_id.lower() or p["name"].lower() == str_id.lower():
                return p
    return None

def get_cart_items():
    cart = session.get("cart", {})
    items = []
    subtotal = 0
    if isinstance(cart, dict):
        for book_id, item_data in cart.items():
            if isinstance(item_data, dict):
                qty = item_data.get("quantity", 1)
                price = item_data.get("price", 0)
                item_subtotal = price * qty
                subtotal += item_subtotal
                items.append({
                    "id": book_id,
                    "name": item_data.get("name", "Book"),
                    "category": item_data.get("category", "General"),
                    "price": price,
                    "image": item_data.get("image", "images/story-store/trick-treat1-img.jpeg"),
                    "quantity": qty,
                    "subtotal": item_subtotal
                })
    return items, subtotal

@app.route("/story-store")
def story_home():
    books = catalog_products()
    cart_items, _ = get_cart_items()
    cart_count = sum(item["quantity"] for item in cart_items)
    return render_template("story_home.html", books=books, cart_count=cart_count)

@app.route("/story-store/categories")
def story_categories():
    books = catalog_products()
    categories = {}
    for b in books:
        cat = b["category"]
        categories[cat] = categories.get(cat, 0) + 1
    cart_items, _ = get_cart_items()
    cart_count = sum(item["quantity"] for item in cart_items)
    return render_template("story_categories.html", categories=categories, books=books, cart_count=cart_count)

@app.route("/story-store/books")
def story_books():
    books = catalog_products()
    cart_items, _ = get_cart_items()
    cart_count = sum(item["quantity"] for item in cart_items)
    return render_template("story_books.html", books=books, cart_count=cart_count)

@app.route("/story-store/book/<book_id>")
def story_book_details(book_id):
    book = get_story_book(book_id)
    if not book:
        abort(404)
    cart_items, _ = get_cart_items()
    cart_count = sum(item["quantity"] for item in cart_items)
    return render_template("story_book_details.html", book=book, cart_count=cart_count)

@app.route("/story-store/cart")
def story_cart():
    cart_items, subtotal = get_cart_items()
    cart_count = sum(item["quantity"] for item in cart_items)
    return render_template("story_cart.html", cart_items=cart_items, subtotal=subtotal, total=subtotal, cart_count=cart_count)

@app.route("/story-store/cart/add", methods=["POST"])
def story_cart_add():
    book_id = request.form.get("book_id")
    try:
        qty = max(1, int(request.form.get("quantity", 1)))
    except ValueError:
        qty = 1
    book = get_story_book(book_id)
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("story_books"))
    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}
    key = str(book["id"])
    if key in cart:
        cart[key]["quantity"] += qty
    else:
        cart[key] = {
            "name": book["name"],
            "category": book["category"],
            "price": book["price"],
            "image": book["image"],
            "quantity": qty
        }
    session["cart"] = cart
    session.modified = True
    flash(f"Added '{book['name']}' to your cart.", "success")
    return redirect(url_for("story_cart"))

@app.route("/story-store/cart/update", methods=["POST"])
def story_cart_update():
    book_id = str(request.form.get("book_id", ""))
    action = request.form.get("action", "")
    cart = session.get("cart", {})
    if isinstance(cart, dict) and book_id in cart:
        if action == "increase":
            cart[book_id]["quantity"] += 1
        elif action == "decrease":
            cart[book_id]["quantity"] -= 1
            if cart[book_id]["quantity"] <= 0:
                del cart[book_id]
        elif action == "remove":
            del cart[book_id]
        elif "quantity" in request.form:
            try:
                new_q = int(request.form.get("quantity"))
                if new_q > 0:
                    cart[book_id]["quantity"] = new_q
                else:
                    del cart[book_id]
            except ValueError:
                pass
        session["cart"] = cart
        session.modified = True
    return redirect(url_for("story_cart"))

@app.route("/story-store/checkout", methods=["GET", "POST"])
def story_checkout():
    cart_items, subtotal = get_cart_items()
    if not cart_items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("story_books"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        if not all([name, email, phone, address, city]):
            flash("Please fill in all shipping details.", "error")
            return render_template("story_checkout.html", cart_items=cart_items, subtotal=subtotal, total=subtotal)
        session["pending_story_order"] = {
            "customer_name": name,
            "email": email,
            "phone": phone,
            "address": f"{address}, {city}",
            "items": ", ".join(f"{i['name']} x {i['quantity']}" for i in cart_items),
            "total": subtotal
        }
        return redirect(url_for("story_payment"))

    customer_info = {}
    if session.get("customer_id"):
        with db_connection() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (session["customer_id"],)).fetchone()
            if cust:
                customer_info = dict(cust)

    cart_count = sum(item["quantity"] for item in cart_items)
    return render_template("story_checkout.html", cart_items=cart_items, subtotal=subtotal, total=subtotal, customer_info=customer_info, cart_count=cart_count)

@app.route("/story-store/payment", methods=["GET", "POST"])
def story_payment():
    cart_items, subtotal = get_cart_items()
    order = session.get("pending_story_order")
    if not order and cart_items:
        order = {
            "customer_name": session.get("customer_name", "Guest Customer"),
            "email": "customer@example.com",
            "phone": "9876543210",
            "address": "Coimbatore, Tamil Nadu",
            "items": ", ".join(f"{i['name']} x {i['quantity']}" for i in cart_items),
            "total": subtotal
        }
    if not order:
        flash("No active order found. Please checkout first.", "error")
        return redirect(url_for("story_books"))

    if request.method == "POST":
        return redirect(url_for("story_order_success"))

    return render_template(
        "story_payment.html",
        order=order,
        cart_items=cart_items,
        amount=order.get("total", subtotal),
        upi_id=UPI_ID,
        cart_count=sum(i["quantity"] for i in cart_items)
    )

@app.route("/story-store/order-success", methods=["GET", "POST"])
def story_order_success():
    order_info = session.pop("pending_story_order", None)
    cart_items, subtotal = get_cart_items()
    if not order_info and cart_items:
        order_info = {
            "customer_name": session.get("customer_name", "Guest Customer"),
            "email": "customer@example.com",
            "phone": "9876543210",
            "address": "Coimbatore, Tamil Nadu",
            "items": ", ".join(f"{i['name']} x {i['quantity']}" for i in cart_items),
            "total": subtotal
        }
    
    order_id = None
    if order_info:
        customer_id = session.get("customer_id")
        payment_method = request.form.get("method", "Razorpay / UPI")
        with db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO orders (customer_name, email, phone, address, items, total, status, payment_status, payment_method, customer_id) VALUES (?, ?, ?, ?, ?, ?, 'New', 'Paid', ?, ?)",
                (order_info["customer_name"], order_info["email"], order_info["phone"], order_info["address"], order_info["items"], order_info["total"], payment_method, customer_id)
            )
            order_id = cur.lastrowid
            subject = f"Order Confirmation - AK CLICKS Story Store (#ORD-{order_id})"
            body = f"Hello {order_info['customer_name']},\n\nThank you for your order!\n\nOrder ID: ORD-{order_id}\nItems: {order_info['items']}\nTotal: ₹{order_info['total']}\n\nWe will ship your books shortly."
            queue_notification(conn, order_info["email"], "email", subject, body)

    # Generate synthetic IDs & delivery date
    order_id_num = order_id or 1001
    payment_id = f"PAY-STORY-{order_id_num}982"
    txn_id = f"TXN-STORY-{order_id_num}441"
    order_date = datetime.now().strftime("%B %d, %Y")
    est_delivery = (datetime.now() + timedelta(days=6)).strftime("%B %d, %Y")

    full_order_details = {
        "order_id": order_id_num,
        "payment_id": payment_id,
        "txn_id": txn_id,
        "order_date": order_date,
        "est_delivery": est_delivery,
        "customer_name": order_info.get("customer_name", "Valued Customer") if order_info else "Valued Customer",
        "email": order_info.get("email", "customer@example.com") if order_info else "customer@example.com",
        "address": order_info.get("address", "Tamil Nadu, India") if order_info else "Tamil Nadu, India",
        "items": order_info.get("items", "Story Books") if order_info else "Story Books",
        "cart_items": cart_items,
        "total": order_info.get("total", subtotal) if order_info else subtotal,
        "payment_method": request.form.get("method", "Razorpay / UPI")
    }

    session.pop("cart", None)
    session.modified = True

    return render_template("story_order_success.html", order=full_order_details, order_id=order_id_num)

@app.route("/story-store/payment/qr")
def story_payment_qr():
    img = qrcode.make("upi://pay?pa=payments@akclicks&pn=AK%20STORY%20STORE&cu=INR")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")

def generate_story_receipt_pdf(order_data):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.HexColor('#ff4820'))
    h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=colors.HexColor('#111111'))
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor('#333333'))
    body_bold = ParagraphStyle('BodyBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, textColor=colors.HexColor('#111111'))
    footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=9, leading=12, textColor=colors.HexColor('#777777'), alignment=1)

    elements = []

    # Brand Header
    elements.append(Paragraph("AK STORY STORE", title_style))
    elements.append(Paragraph("Official Purchase Receipt & Tax Invoice", body_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#ff4820'), spaceAfter=15))

    # Meta Grid (Receipt, Order, Payment IDs)
    receipt_no = f"REC-ORD-{order_data.get('order_id', 1001)}"
    order_no = f"ORD-{order_data.get('order_id', 1001)}"
    txn_id = order_data.get('txn_id', f"TXN-STORY-{order_data.get('order_id', 1001)}")
    pay_id = order_data.get('payment_id', f"PAY-STORY-{order_data.get('order_id', 1001)}")
    date_str = order_data.get('order_date', datetime.now().strftime("%B %d, %Y"))

    meta_data = [
        [Paragraph(f"<b>Receipt No:</b> {receipt_no}", body_style), Paragraph(f"<b>Date:</b> {date_str}", body_style)],
        [Paragraph(f"<b>Order No:</b> {order_no}", body_style), Paragraph(f"<b>Payment Status:</b> <font color='#27ae60'><b>PAID</b></font>", body_style)],
        [Paragraph(f"<b>Transaction ID:</b> {txn_id}", body_style), Paragraph(f"<b>Payment Method:</b> {order_data.get('payment_method', 'Razorpay / UPI')}", body_style)],
        [Paragraph(f"<b>Payment ID:</b> {pay_id}", body_style), Paragraph(f"<b>Estimated Delivery:</b> {order_data.get('est_delivery', '5-7 Business Days')}", body_style)]
    ]
    meta_table = Table(meta_data, colWidths=[270, 270])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f9f9f9')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 15))

    # Customer & Shipping Information
    elements.append(Paragraph("Customer & Shipping Details", h2_style))
    cust_data = [
        [Paragraph(f"<b>Customer Name:</b> {order_data.get('customer_name', 'Guest')}", body_style)],
        [Paragraph(f"<b>Email:</b> {order_data.get('email', 'N/A')}", body_style)],
        [Paragraph(f"<b>Shipping Address:</b> {order_data.get('address', 'N/A')}", body_style)]
    ]
    cust_table = Table(cust_data, colWidths=[540])
    cust_table.setStyle(TableStyle([
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(cust_table)
    elements.append(Spacer(1, 15))

    # Itemized Table
    elements.append(Paragraph("Book Details", h2_style))
    items_header = [Paragraph("<b>Book Title</b>", body_bold), Paragraph("<b>Qty</b>", body_bold), Paragraph("<b>Price</b>", body_bold), Paragraph("<b>Subtotal</b>", body_bold)]
    table_rows = [items_header]

    cart_items = order_data.get("cart_items", [])
    if not cart_items:
        table_rows.append([
            Paragraph(f"<b>{order_data.get('items', 'Story Book')}</b>", body_style),
            Paragraph("1", body_style),
            Paragraph(f"₹{order_data.get('total', 0)}", body_style),
            Paragraph(f"₹{order_data.get('total', 0)}", body_style)
        ])
    else:
        for item in cart_items:
            table_rows.append([
                Paragraph(f"<b>{item['name']}</b><br/><font size=8 color='#666666'>{item.get('category', 'Book')}</font>", body_style),
                Paragraph(str(item['quantity']), body_style),
                Paragraph(f"₹{item['price']}", body_style),
                Paragraph(f"₹{item['subtotal']}", body_style)
            ])

    items_table = Table(table_rows, colWidths=[280, 60, 100, 100])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#222222')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e0e0e0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 15))

    # Totals Summary
    grand_total_val = order_data.get('total', 0)

    totals_data = [
        ["", Paragraph("<b>Subtotal:</b>", body_style), Paragraph(f"₹{grand_total_val}", body_style)],
        ["", Paragraph("<b>Shipping:</b>", body_style), Paragraph("FREE", body_style)],
        ["", Paragraph("<b>Grand Total:</b>", body_bold), Paragraph(f"<b>₹{grand_total_val}</b>", title_style)]
    ]
    totals_table = Table(totals_data, colWidths=[280, 140, 120])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 25))

    # Footer
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#dddddd'), spaceAfter=15))
    elements.append(Paragraph("Thank you for your purchase from AK Story Store!", footer_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph("Generated by AK Story Store &middot; Official Receipt", footer_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

@app.route("/story-store/download-receipt/<int:order_id>")
def story_download_receipt(order_id):
    with db_connection() as conn:
        order_row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order_row:
        flash("Order not found.", "error")
        return redirect(url_for("story_books"))
    
    order = dict(order_row)
    order_data = {
        "order_id": order["id"],
        "customer_name": order["customer_name"],
        "email": order["email"],
        "phone": order["phone"],
        "address": order["address"],
        "items": order["items"],
        "total": order["total"],
        "payment_method": order.get("payment_method", "Razorpay / UPI"),
        "order_date": order.get("created_at", datetime.now().strftime("%B %d, %Y")),
        "txn_id": f"TXN-STORY-{order['id']}441",
        "payment_id": f"PAY-STORY-{order['id']}982",
        "est_delivery": "5 - 7 Business Days"
    }
    
    pdf_buffer = generate_story_receipt_pdf(order_data)
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"AK_Story_Store_Receipt_ORD-{order['id']}.pdf"
    )

# Initialize database
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
