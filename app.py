from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import boto3
import uuid

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Can be stored in environment later

# Initialize DynamoDB (no credentials hardcoded)
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')

# Tables
users_table = dynamodb.Table('tutormatch_users')
tutors_table = dynamodb.Table('tutormatch_tutors')
bookings_table = dynamodb.Table('tutormatch_bookings')
payments_table = dynamodb.Table('tutormatch_payments')


@app.route('/')
def homepage():
    return render_template("homepage.html")


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        try:
            existing = users_table.get_item(Key={'email': email})
            if 'Item' in existing:
                return "User already exists", 400
            users_table.put_item(Item={
                'email': email,
                'name': name,
                'password': password
            })
            return redirect(url_for('login'))
        except Exception as e:
            return str(e), 500
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = users_table.get_item(Key={'email': email}).get('Item')
        if user and user['password'] == password:
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
    return render_template('login.html')


@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")


@app.route('/tutor-search')
def tutor_search():
    tutors = tutors_table.scan().get('Items', [])
    return render_template("tutor_search.html", tutors=tutors)


@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    tutor = tutors_table.get_item(Key={'id': tutor_id}).get('Item')
    if not tutor:
        abort(404)
    return render_template("tutor_profile.html", tutor=tutor)


@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    tutor = tutors_table.get_item(Key={'id': tutor_id}).get('Item')
    if not tutor:
        abort(404)

    if request.method == 'POST':
        booking_id = str(uuid.uuid4())
        booking_data = {
            "id": booking_id,
            "tutor_id": tutor_id,
            "tutor_name": tutor.get("name"),
            "date": request.form['date'],
            "time": request.form['time'],
            "subject": request.form['subject'],
            "session_type": request.form.get('session_type', 'Single'),
            "sessions_count": int(request.form.get('sessions_count', 1)),
            "total_price": int(tutor['rate']) * int(request.form.get('sessions_count', 1)),
            "learning_goals": request.form.get('learning_goals', ''),
            "session_format": request.form.get('session_format', 'Online'),
            "status": "pending_payment",
            "created_at": datetime.now().isoformat()
        }
        bookings_table.put_item(Item=booking_data)
        return redirect(url_for("payment", booking_id=booking_id))

    return render_template("booksession.html", tutor=tutor)


@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={'id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return render_template("payment.html", booking=booking)


@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    email = request.form['email']
    phone = request.form['phone']
    method = request.form['payment_method']

    booking = bookings_table.get_item(Key={'id': booking_id}).get('Item')
    if not booking:
        abort(404)

    payment_id = str(uuid.uuid4())
    payment = {
        "id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "payment_method": method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }

    # Save payment
    payments_table.put_item(Item=payment)

    # Update booking status
    booking["status"] = "confirmed"
    booking["payment_id"] = payment_id
    bookings_table.put_item(Item=booking)

    return redirect(url_for("confirmation", booking_id=booking_id))


@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={'id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return render_template("confirmation.html", booking=booking)


@app.route('/api/student-data')
def student_data():
    bookings_data = bookings_table.scan().get('Items', [])
    payments_data = payments_table.scan().get('Items', [])
    student_bookings = []
    student_payments = []
    notifications = []

    for b in bookings_data:
        student_bookings.append({
            "id": b["id"],
            "tutor_name": b["tutor_name"],
            "subject": b["subject"],
            "date": b["date"],
            "time": b["time"],
            "status": b["status"],
            "total_price": b["total_price"],
            "session_format": b["session_format"],
            "created_at": b["created_at"]
        })
        if b.get("payment_id"):
            p = next((p for p in payments_data if p["id"] == b["payment_id"]), None)
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
                "message": f"Your session with {b['tutor_name']} is confirmed.",
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
    tutor_count = tutors_table.scan(Select='COUNT')['Count']
    return jsonify({"status": "healthy", "tutors_count": tutor_count})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
