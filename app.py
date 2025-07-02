from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
from decimal import Decimal
import boto3
import uuid
import os
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS config
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
sns = boto3.client('sns', region_name='ap-south-1')
sns_topic_arn = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

users_table = dynamodb.Table('Users')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')

# Load tutors from local JSON
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
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
            response = users_table.get_item(Key={'email': email})
            user = response.get('Item')
            if user and user.get('password') == password:
                return redirect(url_for('student_dashboard', student_email=email))
            return "Invalid credentials", 401
        except Exception as e:
            print("Login Error:", e)
            return "Internal server error", 500
    return render_template("login.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        try:
            users_table.put_item(Item={'email': email, 'password': password, 'name': name})
            return redirect(url_for('login'))
        except Exception as e:
            print("DynamoDB Register Error:", e)
            return "Registration failed", 500
    return render_template("register.html")

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    return render_template("tutor_search.html", tutors_with_id=[{"id": k, **v} for k, v in tutors_data.items()])

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
        try:
            booking_id = str(uuid.uuid4())
            date = request.form['date']
            time = request.form['time']
            subject = request.form['subject']
            session_type = request.form.get('session_type', 'Single Session')
            sessions_count = int(request.form.get('sessions_count', 1))
            total_price = Decimal(str(tutor.get('rate', 25))) * sessions_count
            learning_goals = request.form.get('learning_goals', '')
            session_format = request.form.get('session_format', 'Online Video Call')

            booking_data = {
                "booking_id": booking_id,
                "tutor_id": tutor_id,
                "date": date,
                "time": time,
                "subject": subject,
                "session_type": session_type,
                "sessions_count": sessions_count,
                "total_price": total_price,
                "learning_goals": learning_goals,
                "session_format": session_format,
                "status": "pending_payment",
                "created_at": datetime.now().isoformat()
            }

            bookings_table.put_item(Item=booking_data)
            return redirect(url_for("payment", booking_id=booking_id))
        except Exception as e:
            print("Booking Error:", e)
            return "Booking failed", 500

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            abort(404)
        tutor = tutors_data.get(booking['tutor_id'], {})
        return render_template("payment.html", booking=booking, booking_id=booking_id, tutor=tutor)
    except Exception as e:
        print("Payment Load Error:", e)
        return "Error loading payment page", 500

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form['payment_method']
    email = request.form['email']
    phone = request.form['phone']

    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            abort(404)

        payment_id = str(uuid.uuid4())
        payment_record = {
            "payment_id": payment_id,
            "booking_id": booking_id,
            "amount": Decimal(str(booking["total_price"])),
            "payment_method": payment_method,
            "status": "completed",
            "created_at": datetime.now().isoformat()
        }

        payments_table.put_item(Item=payment_record)

        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="set #s = :s, payment_id = :p",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "confirmed", ":p": payment_id}
        )

        sns.publish(
            TopicArn=sns_topic_arn,
            Message=f"Session with tutor {booking['tutor_id']} confirmed for {booking['date']} at {booking['time']}.",
            Subject="Session Confirmation"
        )

        return redirect(url_for('confirmation', booking_id=booking_id))
    except Exception as e:
        print("Payment Error:", e)
        return "Payment processing failed", 500

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            abort(404)
        tutor = tutors_data.get(booking['tutor_id'], {})
        return render_template("confirmation.html", booking=booking, tutor=tutor)
    except Exception as e:
        print("Confirmation Error:", e)
        return "Confirmation page failed", 500

@app.route('/api/student-data')
def student_data():
    student_email = request.args.get('student_email')
    try:
        all_bookings = bookings_table.scan().get("Items", [])
        all_payments = payments_table.scan().get("Items", [])

        student_bookings = []
        student_payments = []
        notifications = []

        for b in all_bookings:
            if b.get("status") == "confirmed":
                tutor = tutors_data.get(b["tutor_id"], {})
                student_bookings.append({
                    "id": b["booking_id"],
                    "tutor_name": tutor.get("name", "Unknown"),
                    "subject": b["subject"],
                    "date": b["date"],
                    "time": b["time"],
                    "status": b["status"],
                    "total_price": str(b["total_price"]),
                    "session_format": b["session_format"],
                    "created_at": b["created_at"]
                })
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your session with {tutor.get('name', 'Tutor')} is confirmed.",
                    "date": datetime.now().strftime("%Y-%m-%d")
                })

        for p in all_payments:
            student_payments.append({
                "id": p["payment_id"],
                "amount": str(p["amount"]),
                "status": p["status"],
                "method": p["payment_method"],
                "date": p["created_at"]
            })

        return jsonify({
            "bookings": student_bookings,
            "payments": student_payments,
            "notifications": notifications
        })

    except Exception as e:
        print("Student Data Error:", e)
        return jsonify({"error": "Unable to load student data"}), 500

@app.route('/logout')
def logout():
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "tutors_count": len(tutors_data)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
