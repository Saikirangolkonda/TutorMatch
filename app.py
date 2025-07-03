# app.py for TutorMatch with AWS DynamoDB + SNS integration

from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import boto3
import os
import uuid
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS resources
REGION = 'ap-south-1'
dynamodb = boto3.resource('dynamodb', region_name=REGION)
sns = boto3.client('sns', region_name=REGION)
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# DynamoDB tables
tutor_table = dynamodb.Table('Tutors')
user_table = dynamodb.Table('Users')
booking_table = dynamodb.Table('Bookings')
payment_table = dynamodb.Table('Payments')

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
            user_table.put_item(
                Item={"email": email, "password": password, "name": name},
                ConditionExpression='attribute_not_exists(email)'
            )
            return redirect(url_for('login'))
        except:
            return "User already exists", 400

    return render_template("register.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        res = user_table.get_item(Key={"email": email})
        user = res.get("Item")

        if user and user.get("password") == password:
            return redirect(url_for("student_dashboard"))
        return "Invalid credentials", 401

    return render_template("login.html")

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    tutors = tutor_table.scan().get("Items", [])
    return render_template("tutor_search.html", tutors_with_id=tutors)

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    tutor = tutor_table.get_item(Key={"tutor_id": tutor_id}).get("Item")
    if not tutor:
        abort(404)
    return render_template("tutor_profile.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    tutor = tutor_table.get_item(Key={"tutor_id": tutor_id}).get("Item")
    if not tutor:
        abort(404)

    if request.method == 'POST':
        booking_id = str(uuid.uuid4())
        data = {
            "booking_id": booking_id,
            "tutor_id": tutor_id,
            "date": request.form['date'],
            "time": request.form['time'],
            "subject": request.form['subject'],
            "session_type": request.form.get('session_type', 'Single Session'),
            "sessions_count": int(request.form.get('sessions_count', 1)),
            "learning_goals": request.form.get('learning_goals', ''),
            "session_format": request.form.get('session_format', 'Online Video Call'),
            "status": "pending_payment",
            "total_price": tutor['rate'] * int(request.form.get('sessions_count', 1)),
            "created_at": datetime.now().isoformat(),
            "tutor_name": tutor['name']
        }
        booking_table.put_item(Item=data)
        return redirect(url_for('payment', booking_id=booking_id))

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get("booking_id")
    booking = booking_table.get_item(Key={"booking_id": booking_id}).get("Item")
    if not booking:
        abort(404)
    return render_template("payment.html", booking=booking)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    email = request.form['email']
    phone = request.form['phone']
    method = request.form['payment_method']

    booking = booking_table.get_item(Key={"booking_id": booking_id}).get("Item")
    if not booking:
        abort(404)

    payment_id = str(uuid.uuid4())
    payment_table.put_item(Item={
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking['total_price'],
        "payment_method": method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    })

    booking_table.update_item(
        Key={"booking_id": booking_id},
        UpdateExpression="set #s = :s, payment_id = :pid",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "confirmed", ":pid": payment_id}
    )

    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Message=f"Booking Confirmed with {booking['tutor_name']} on {booking['date']} at {booking['time']}",
        Subject="TutorMatch Session Confirmation"
    )

    return redirect(url_for("confirmation", booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get("booking_id")
    booking = booking_table.get_item(Key={"booking_id": booking_id}).get("Item")
    return render_template("confirmation.html", booking=booking)

@app.route('/api/student-data')
def student_data():
    bookings = booking_table.scan().get("Items", [])
    payments = payment_table.scan().get("Items", [])
    notifications = [
        {
            "type": "success",
            "title": "Session Confirmed",
            "message": f"Your session with {b['tutor_name']} is confirmed.",
            "date": datetime.now().strftime("%Y-%m-%d")
        } for b in bookings if b.get("status") == "confirmed"
    ]
    return jsonify({"bookings": bookings, "payments": payments, "notifications": notifications})

@app.route('/logout')
def logout():
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
