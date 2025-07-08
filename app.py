from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import uuid
import json
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# Load tutors from JSON file
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
if os.path.exists(TUTORS_FILE):
    with open(TUTORS_FILE) as f:
        tutors_data = json.load(f)
else:
    tutors_data = {}  # fallback

# In-memory storage for demo
users = {}
bookings = {}
payments = {}

@app.route('/')
def homepage():
    return render_template("homepage.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        if email in users:
            return "User already exists", 400
        users[email] = {"email": email, "password": password, "name": name}
        return redirect(url_for('login'))
    return render_template("register.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = users.get(email)
        if user and user['password'] == password:
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
    return render_template("login.html")

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    # Pass tutors with their IDs for display
    tutors = [{"id": tid, **info} for tid, info in tutors_data.items()]
    return render_template("tutor_search.html", tutors=tutors)

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        abort(404)
    return render_template("tutor_profile.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        abort(404)

    if request.method == 'POST':
        booking_id = str(uuid.uuid4())
        sessions_count = int(request.form.get('sessions_count', 1))
        total_price = tutor.get("rate", 25) * sessions_count

        bookings[booking_id] = {
            "id": booking_id,
            "tutor_id": tutor_id,
            "tutor_data": tutor,
            "date": request.form['date'],
            "time": request.form['time'],
            "subject": request.form['subject'],
            "session_type": request.form.get('session_type', 'Single'),
            "sessions_count": sessions_count,
            "learning_goals": request.form.get('learning_goals', ''),
            "session_format": request.form.get('session_format', 'Online'),
            "total_price": total_price,
            "status": "pending_payment",
            "created_at": datetime.now().isoformat()
        }

        return redirect(url_for("payment", booking_id=booking_id))

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get("booking_id")
    booking = bookings.get(booking_id)
    if not booking:
        abort(404)
    return render_template("payment.html", booking=booking)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form.get('booking_id')
    email = request.form.get('email')
    phone = request.form.get('phone')
    payment_method = request.form.get('payment_method')

    # Debug print
    print("Received Payment Form Data:")
    print("Booking ID:", booking_id)
    print("Email:", email)
    print("Phone:", phone)
    print("Payment Method:", payment_method)

    if not booking_id or not email or not phone or not payment_method:
        return "Missing fields in form submission", 400

    booking = bookings.get(booking_id)
    if not booking:
        return "Booking not found", 404

    payment_id = str(uuid.uuid4())
    payments[payment_id] = {
        "id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "payment_method": payment_method,
        "email": email,
        "phone": phone,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }

    booking["status"] = "confirmed"
    booking["payment_id"] = payment_id

    return redirect(url_for('confirmation', booking_id=booking_id))



@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get("booking_id")
    booking = bookings.get(booking_id)
    if not booking:
        abort(404)
    return render_template("confirmation.html", booking=booking)

@app.route('/api/student-data')
def student_data():
    student_bookings = []
    student_payments = []
    notifications = []

    for b in bookings.values():
        student_bookings.append({
            "id": b["id"],
            "tutor_name": b["tutor_data"]["name"],
            "subject": b["subject"],
            "date": b["date"],
            "time": b["time"],
            "status": b["status"],
            "total_price": b["total_price"],
            "session_format": b["session_format"],
            "created_at": b["created_at"]
        })

        if b.get("payment_id"):
            p = payments.get(b["payment_id"])
            if p:
                student_payments.append({
                    "id": p["id"],
                    "amount": p["amount"],
                    "status": p["status"],
                    "method": p["payment_method"],
                    "date": p["created_at"]
                })

        if b["status"] == "confirmed":
            notifications.append({
                "type": "success",
                "title": "Session Confirmed",
                "message": f"Your session with {b['tutor_data']['name']} is confirmed.",
                "date": datetime.now().strftime("%Y-%m-%d")
            })

    return jsonify({
        "bookings": student_bookings,
        "payments": student_payments,
        "notifications": notifications
    })

@app.route('/logout')
def logout():
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "tutors_count": len(tutors_data)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
