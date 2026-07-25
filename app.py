import io
import os
import sqlite3
from collections import Counter
from datetime import datetime
from urllib.parse import urlencode

import qrcode
import qrcode.image.svg
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
with app.app_context():
    init_db()
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-before-production")
BOOKING_DEPOSIT = int(os.environ.get("BOOKING_DEPOSIT", "2000"))
UPI_ID = os.environ.get("UPI_ID", "your-upi-id@bank")

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
    return table, record, BOOKING_DEPOSIT if kind == "booking" else record["total"]

@app.route("/")
def home(): return render_template("index.html", products=catalog_products(), year=datetime.now().year)

@app.route("/availability")
def availability():
    date = request.args.get("date", "")
    with db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM bookings WHERE booking_date=? AND status != 'Declined'", (date,)).fetchone()[0]
    return jsonify({"date": date, "available": count == 0, "message": "Available to enquire" if count == 0 else "This date already has a booking enquiry."})

@app.route("/book", methods=["POST"])
def book():
    fields = {key: request.form.get(key, "").strip() for key in ("name","email","phone","service","booking_date","location","message")}
    if not all(fields[key] for key in ("name","email","phone","service","booking_date")):
        flash("Please complete all required booking details.", "error"); return redirect(url_for("home") + "#booking")
    with db_connection() as conn:
        cursor = conn.execute("INSERT INTO bookings (name,email,phone,service,booking_date,location,message) VALUES (:name,:email,:phone,:service,:booking_date,:location,:message)", fields)
        booking_id = cursor.lastrowid
        queue_notification(conn, fields["email"], "email", "Booking enquiry received", f"Your {fields['service']} enquiry is recorded. Booking reference: {booking_id}.")
    return redirect(url_for("payment", kind="booking", record_id=booking_id))

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
        cursor = conn.execute("INSERT INTO orders (customer_name,email,phone,address,items,total,customer_id) VALUES (?,?,?,?,?,?,?)", (*customer.values(), total, session.get("customer_id")))
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
    if request.method == "POST":
        action = request.form.get("action"); email = request.form.get("email", "").strip().lower(); password = request.form.get("password", "")
        with db_connection() as conn:
            if action == "register":
                name = request.form.get("name", "").strip()
                if not name or not email or len(password) < 6: flash("Use a name, valid email and at least 6-character password.", "error")
                elif conn.execute("SELECT 1 FROM customers WHERE email=?", (email,)).fetchone(): flash("An account already uses this email.", "error")
                else:
                    cursor=conn.execute("INSERT INTO customers (name,email,password_hash) VALUES (?,?,?)",(name,email,generate_password_hash(password))); session["customer_id"]=cursor.lastrowid; session["customer_name"]=name; return redirect(url_for("account"))
            else:
                customer=conn.execute("SELECT * FROM customers WHERE email=?",(email,)).fetchone()
                if customer and check_password_hash(customer["password_hash"], password): session["customer_id"]=customer["id"];session["customer_name"]=customer["name"];return redirect(url_for("account"))
                flash("Invalid email or password.", "error")
    orders=[]
    if session.get("customer_id"):
        with db_connection() as conn: orders=conn.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC",(session["customer_id"],)).fetchall()
    return render_template("account.html", orders=orders)

@app.route("/account/logout")
def customer_logout(): session.pop("customer_id",None);session.pop("customer_name",None);return redirect(url_for("home"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form.get("username")==os.environ.get("ADMIN_USERNAME","admin") and request.form.get("password")==os.environ.get("ADMIN_PASSWORD","1234"): session["admin"]=True;return redirect(url_for("admin"))
        flash("Invalid username or password.","error")
    return render_template("admin.html")

@app.route("/admin")
def admin():
    if not session.get("admin"): return redirect(url_for("login"))
    with db_connection() as conn:
        bookings=conn.execute("SELECT * FROM bookings ORDER BY id DESC").fetchall(); orders=conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall(); products=conn.execute("SELECT * FROM products ORDER BY name").fetchall(); notifications=conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 20").fetchall()
    return render_template("dashboard.html",bookings=bookings,orders=orders,products=products,notifications=notifications)

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
    if request.form.get("status") in {"Pending","Approved","Declined"}:
        with db_connection() as conn: conn.execute("UPDATE bookings SET status=? WHERE id=?",(request.form["status"],booking_id))
    return redirect(url_for("admin"))

@app.route("/order/<int:order_id>/status",methods=["POST"])
def update_order(order_id):
    if not session.get("admin"): return redirect(url_for("login"))
    if request.form.get("status") in {"New","Processing","Fulfilled"}:
        with db_connection() as conn: conn.execute("UPDATE orders SET status=? WHERE id=?",(request.form["status"],order_id))
    return redirect(url_for("admin"))

@app.route("/logout")
def logout(): session.clear();return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
