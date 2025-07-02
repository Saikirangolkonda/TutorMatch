from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import os, json, uuid

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# Load tutor data from JSON
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
if os.path.exists(TUTORS_FILE):
    with open(TUTORS_FILE) as f:
        tutors_data = json.load(f)
else:
    tutors_data = {}  # Empty fallback

# In-memory storage
users = {}
bookings = {}
payments = {}

@app.route('/')
def homepage():
    return render_template("homepage.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in users and users[email]['password'] == password:
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
    return render_template('login.html')

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
    return render_template('register.html')

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    tutors_with_id = [{"id": tid, **info} for tid, info in tutors_data.items()]
    return render_template("tutor_search.html", tutors_with_id=tutors_with_id)

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
        date = request.form['date']
        time = request.form['time']
        subject = request.form['subject']
        session_type = request.form.get('session_type', 'Single Session')
        sessions_count = int(request.form.get('sessions_count', 1))
        total_price = tutor.get('rate', 25) * sessions_count
        learning_goals = request.form.get('learning_goals', '')
        session_format = request.form.get('session_format', 'Online Video Call')

        bookings[booking_id] = {
            "id": booking_id, "tutor_id": tutor_id, "tutor_data": tutor,
            "date": date, "time": time, "subject": subject,
            "session_type": session_type, "sessions_count": sessions_count,
            "total_price": total_price, "learning_goals": learning_goals,
            "session_format": session_format, "status": "pending_payment",
            "created_at": datetime.now().isoformat()
        }
        return redirect(url_for("payment", booking_id=booking_id))

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    booking = bookings.get(booking_id)
    if not booking:
        abort(404)
    return render_template("payment.html", booking=booking, booking_id=booking_id)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form['payment_method']
    email = request.form['email']
    phone = request.form['phone']
    if booking_id not in bookings:
        abort(404)
    payment_id = str(uuid.uuid4())
    payments[payment_id] = {
        "id": payment_id,
        "booking_id": booking_id,
        "amount": bookings[booking_id]["total_price"],
        "payment_method": payment_method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }
    bookings[booking_id]["status"] = "confirmed"
    bookings[booking_id]["payment_id"] = payment_id
    return redirect(url_for('confirmation', booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
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
            "id": b["id"], "tutor_name": b["tutor_data"]["name"], "subject": b["subject"],
            "date": b["date"], "time": b["time"], "status": b["status"],
            "total_price": b["total_price"], "session_format": b["session_format"],
            "created_at": b["created_at"]
        })
        if "payment_id" in b and b["payment_id"] in payments:
            p = payments[b["payment_id"]]
            student_payments.append({
                "id": p["id"], "amount": p["amount"],
                "status": p["status"], "method": p["payment_method"],
                "date": p["created_at"]
            })
        if b["status"] == "confirmed":
            notifications.append({
                "type": "success", "title": "Session Confirmed",
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
    return jsonify({"status": "healthy", "tutors_count": len(tutors_data)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
