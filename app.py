from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime, timedelta
import os, json, uuid

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# Load tutor data
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
if os.path.exists(TUTORS_FILE):
    with open(TUTORS_FILE) as f:
        tutors_data = json.load(f)
else:
    tutors_data = {
        "tutor1": {
            "name": "John Smith",
            "subjects": ["Mathematics", "Physics"],
            "rate": 30,
            "rating": 4.8,
            "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
            "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"]
        },
        "tutor2": {
            "name": "Sarah Johnson",
            "subjects": ["English", "Literature"],
            "rate": 25,
            "rating": 4.6,
            "bio": "English literature specialist, helping students excel in writing and analysis.",
            "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"]
        }
    }
    os.makedirs("templates", exist_ok=True)
    with open(TUTORS_FILE, "w") as f:
        json.dump(tutors_data, f, indent=2)

# In-memory storage
users = {}
bookings = {}
payments = {}

@app.route('/')
def homepage():
    try:
        return render_template("homepage.html")
    except:
        return """
        <h1>Welcome to TutorMatch</h1>
        <a href='/login'>Login</a> | <a href='/register'>Register</a>
        """

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in users and users[email]['password'] == password:
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
    try:
        return render_template('login.html')
    except:
        return '''
            <h1>Login</h1>
            <form method="post">
            Email: <input name="email"><br>
            Password: <input name="password"><br>
            <button type="submit">Login</button>
            </form>
        '''

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        if email in users:
            return "User already exists", 400
        users[email] = {
            "email": email, "password": password, "name": name
        }
        return redirect(url_for('login'))
    try:
        return render_template('register.html')
    except:
        return '''
            <h1>Register</h1>
            <form method="post">
            Name: <input name="name"><br>
            Email: <input name="email"><br>
            Password: <input name="password"><br>
            <button type="submit">Register</button>
            </form>
        '''

@app.route('/student-dashboard')
def student_dashboard():
    try:
        return render_template("student_dashboard.html")
    except:
        return '''
        <h1>Student Dashboard</h1>
        <a href="/tutor-search">Search Tutors</a>
        '''

@app.route('/tutor-search')
def tutor_search():
    try:
        return render_template("tutor_search.html", tutors_with_id=[{"id": k, **v} for k, v in tutors_data.items()])
    except:
        html = ""
        for tid, t in tutors_data.items():
            html += f"<h3>{t['name']}</h3><a href='/tutor-profile/{tid}'>View Profile</a><hr>"
        return f"<h1>Find Tutors</h1>{html}"

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        abort(404)
    try:
        return render_template("tutor_profile.html", tutor=tutor, tutor_id=tutor_id)
    except:
        return f"<h1>{tutor['name']}</h1><a href='/book-session/{tutor_id}'>Book Session</a>"

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
    try:
        return render_template("payment.html", booking=booking, booking_id=booking_id)
    except:
        return f"<h1>Pay ${booking['total_price']}</h1><form method='post' action='/process-payment'><input name='booking_id' value='{booking_id}'><button>Pay</button></form>"

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
    try:
        return render_template("confirmation.html", booking=booking)
    except:
        return f"<h1>Booking Confirmed</h1><p>Session with {booking['tutor_data']['name']} confirmed.</p>"

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
