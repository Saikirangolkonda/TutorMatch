from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import boto3
import uuid
import os
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS Setup
region_name = 'us-east-1'
dynamodb = boto3.resource('dynamodb', region_name=region_name)
sns = boto3.client('sns', region_name='ap-south-1')
sns_topic_arn = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# DynamoDB tables
users_table = dynamodb.Table('Users')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')
tutors_table = dynamodb.Table('Tutors')

# Load local tutor data as fallback
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
if os.path.exists(TUTORS_FILE):
    with open(TUTORS_FILE) as f:
        tutors_data = json.load(f)
else:
    tutors_data = {}

@app.route('/')
def homepage():
    return render_template("homepage.html")

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

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        try:
            users_table.put_item(Item={'email': email, 'password': password, 'name': name})
        except Exception as e:
            return f"Error: {e}", 500
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    try:
        response = tutors_table.scan()
        tutor_list = response.get('Items', [])
    except:
        tutor_list = [{"id": k, **v} for k, v in tutors_data.items()]
    return render_template("tutor_search.html", tutors_with_id=tutor_list)

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    try:
        tutor = tutors_table.get_item(Key={'tutor_id': tutor_id}).get('Item')
    except:
        tutor = tutors_data.get(tutor_id)
    if not tutor:
        abort(404)
    return render_template("tutor_profile.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    tutor = tutors_table.get_item(Key={'tutor_id': tutor_id}).get('Item')
    if not tutor:
        abort(404)

    if request.method == 'POST':
        booking_id = str(uuid.uuid4())
        booking = {
            "booking_id": booking_id,
            "tutor_id": tutor_id,
            "date": request.form['date'],
            "time": request.form['time'],
            "subject": request.form['subject'],
            "session_type": request.form.get('session_type', 'Single Session'),
            "sessions_count": int(request.form.get('sessions_count', 1)),
            "total_price": tutor['rate'] * int(request.form.get('sessions_count', 1)),
            "learning_goals": request.form.get('learning_goals', ''),
            "session_format": request.form.get('session_format', 'Online Video Call'),
            "status": "pending_payment",
            "created_at": datetime.utcnow().isoformat()
        }
        bookings_table.put_item(Item=booking)
        return redirect(url_for("payment", booking_id=booking_id))
    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return render_template("payment.html", booking=booking, booking_id=booking_id)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)

    payment_id = str(uuid.uuid4())
    payment = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking['total_price'],
        "payment_method": request.form['payment_method'],
        "status": "completed",
        "created_at": datetime.utcnow().isoformat()
    }

    # Save payment
    payments_table.put_item(Item=payment)

    # Update booking
    booking['status'] = "confirmed"
    booking['payment_id'] = payment_id
    bookings_table.put_item(Item=booking)

    # SNS notification
    message = f"Session with Tutor {booking['tutor_id']} confirmed on {booking['date']} at {booking['time']}."
    sns.publish(TopicArn=sns_topic_arn, Message=message, Subject="TutorMatch Session Confirmed")

    return redirect(url_for('confirmation', booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return render_template("confirmation.html", booking=booking)

@app.route('/api/student-data')
def student_data():
    bookings_resp = bookings_table.scan()
    payments_resp = payments_table.scan()
    student_bookings = bookings_resp.get('Items', [])
    student_payments = payments_resp.get('Items', [])
    notifications = [{
        "type": "success",
        "title": "Session Confirmed",
        "message": f"Your session with Tutor {b['tutor_id']} is confirmed.",
        "date": datetime.utcnow().strftime("%Y-%m-%d")
    } for b in student_bookings if b['status'] == 'confirmed']

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
    tutor_count = tutors_table.scan(Select='COUNT').get('Count', 0)
    return jsonify({"status": "healthy", "tutors_count": tutor_count})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
