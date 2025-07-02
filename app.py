from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import boto3
import uuid
import os
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS Region
region = 'ap-south-1'

# AWS Clients
dynamodb = boto3.resource('dynamodb', region_name=region)
sns = boto3.client('sns', region_name=region)
sns_topic_arn = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# DynamoDB Tables
users_table = dynamodb.Table('Users')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')

# Tutor data from JSON
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
tutors_data = {}
if os.path.exists(TUTORS_FILE):
    with open(TUTORS_FILE) as f:
        tutors_data = json.load(f)

@app.route('/')
def homepage():
    return render_template("homepage.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = users_table.get_item(Key={'email': email}).get('Item')
            if user and user['password'] == password:
                return redirect(url_for('student_dashboard'))
            return "Invalid credentials", 401
        except Exception as e:
            print("Login error:", e)
            return "Internal Server Error", 500
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        try:
            users_table.put_item(Item={
                'email': email,
                'password': password,
                'name': name
            })
            return redirect(url_for('login'))
        except Exception as e:
            print("Register error:", e)
            return "Internal Server Error", 500
    return render_template('register.html')

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    tutors_list = [{"id": k, **v} for k, v in tutors_data.items()]
    return render_template("tutor_search.html", tutors_with_id=tutors_list)

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
        try:
            session_type = request.form.get('session_type', 'Single Session')
            sessions_count = int(request.form.get('sessions_count', 1))
            total_price = tutor.get('rate', 25) * sessions_count

            booking = {
                "booking_id": booking_id,
                "tutor_id": tutor_id,
                "date": request.form['date'],
                "time": request.form['time'],
                "subject": request.form['subject'],
                "session_type": session_type,
                "sessions_count": sessions_count,
                "total_price": total_price,
                "learning_goals": request.form.get('learning_goals', ''),
                "session_format": request.form.get('session_format', 'Online Video Call'),
                "status": "pending_payment",
                "created_at": datetime.utcnow().isoformat(),
                "tutor_data": tutor  # ✅ include tutor details directly
            }
            bookings_table.put_item(Item=booking)
            return redirect(url_for("payment", booking_id=booking_id))
        except Exception as e:
            print("Booking Error:", e)
            return f"Error while booking: {e}", 500

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    try:
        booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
        if not booking:
            abort(404)

        # Safety fallback (in case tutor_data is missing)
        if 'tutor_data' not in booking:
            booking['tutor_data'] = tutors_data.get(booking['tutor_id'], {})

        return render_template("payment.html", booking=booking, booking_id=booking_id)
    except Exception as e:
        print("Payment Load Error:", e)
        return "Internal Server Error", 500

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form['payment_method']
    email = request.form['email']
    phone = request.form['phone']

    try:
        booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
        if not booking:
            abort(404)

        payment_id = str(uuid.uuid4())
        payment = {
            "payment_id": payment_id,
            "booking_id": booking_id,
            "amount": booking['total_price'],
            "payment_method": payment_method,
            "status": "completed",
            "created_at": datetime.utcnow().isoformat()
        }
        payments_table.put_item(Item=payment)

        # Update booking with confirmed status
        booking['status'] = "confirmed"
        booking['payment_id'] = payment_id
        bookings_table.put_item(Item=booking)

        tutor_name = booking.get('tutor_data', {}).get('name', f"Tutor {booking['tutor_id']}")

        # Send SNS notification
        sns.publish(
            TopicArn=sns_topic_arn,
            Message=f"Your session with {tutor_name} is confirmed on {booking['date']} at {booking['time']}.",
            Subject="TutorMatch Booking Confirmed"
        )

        return redirect(url_for('confirmation', booking_id=booking_id))

    except Exception as e:
        print("Payment Processing Error:", e)
        return f"Payment Error: {e}", 500

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    try:
        booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
        if not booking:
            abort(404)

        # Ensure tutor data present
        if 'tutor_data' not in booking:
            booking['tutor_data'] = tutors_data.get(booking['tutor_id'], {})

        return render_template("confirmation.html", booking=booking)
    except Exception as e:
        print("Confirmation Error:", e)
        return "Internal Server Error", 500

@app.route('/api/student-data')
def student_data():
    try:
        bookings = bookings_table.scan().get('Items', [])
        payments = payments_table.scan().get('Items', [])

        student_bookings = []
        student_payments = []
        notifications = []

        for b in bookings:
            student_bookings.append({
                "id": b["booking_id"],
                "tutor_name": b.get("tutor_data", {}).get("name", "Unknown"),
                "subject": b["subject"],
                "date": b["date"],
                "time": b["time"],
                "status": b["status"],
                "total_price": b["total_price"],
                "session_format": b["session_format"],
                "created_at": b["created_at"]
            })
            if b.get("payment_id"):
                p = next((x for x in payments if x['payment_id'] == b['payment_id']), None)
                if p:
                    student_payments.append({
                        "id": p["payment_id"],
                        "amount": p["amount"],
                        "status": p["status"],
                        "method": p["payment_method"],
                        "date": p["created_at"]
                    })
            if b["status"] == "confirmed":
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your session with {b.get('tutor_data', {}).get('name', 'your tutor')} is confirmed.",
                    "date": datetime.utcnow().strftime("%Y-%m-%d")
                })

        return jsonify({
            "bookings": student_bookings,
            "payments": student_payments,
            "notifications": notifications
        })
    except Exception as e:
        print("Student Data Error:", e)
        return "Internal Server Error", 500

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
    app.run(host='0.0.0.0', port=5000)
