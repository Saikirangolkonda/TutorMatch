from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import boto3
import uuid
import json
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS config
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
sns_client = boto3.client('sns', region_name='ap-south-1')
SNS_TOPIC_ARN = "arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications"

# DynamoDB tables
users_table = dynamodb.Table('Users')
tutors_table = dynamodb.Table('Tutors')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')

# Load local tutors JSON
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
        user = users_table.get_item(Key={'email': email}).get('Item')
        if user and user.get("password") == password:
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
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
            return f"Error: {str(e)}"
    return render_template("register.html")

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    tutors_with_id = [{"id": k, **v} for k, v in tutors_data.items()]
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
        booking = {
            "booking_id": booking_id,
            "tutor_id": tutor_id,
            "email": request.form['email'],
            "date": request.form['date'],
            "time": request.form['time'],
            "subject": request.form['subject'],
            "session_type": request.form.get('session_type', 'Single'),
            "sessions_count": int(request.form.get('sessions_count', 1)),
            "total_price": tutor['rate'] * int(request.form.get('sessions_count', 1)),
            "learning_goals": request.form.get('learning_goals', ''),
            "session_format": request.form.get('session_format', 'Online'),
            "status": "pending_payment",
            "created_at": datetime.now().isoformat()
        }
        bookings_table.put_item(Item=booking)
        return redirect(url_for("payment", booking_id=booking_id))
    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={"booking_id": booking_id}).get("Item")
    if not booking:
        abort(404)
    return render_template("payment.html", booking=booking)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_id = str(uuid.uuid4())
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get("Item")

    payment = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "payment_method": request.form['payment_method'],
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }
    payments_table.put_item(Item=payment)

    bookings_table.update_item(
        Key={"booking_id": booking_id},
        UpdateExpression="SET #s = :s, payment_id = :p",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "confirmed", ":p": payment_id}
    )

    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="Session Confirmed!",
            Message=f"Your session with {booking['tutor_id']} on {booking['date']} at {booking['time']} is confirmed."
        )
    except Exception as e:
        print(f"Failed to send SNS: {e}")

    return redirect(url_for("confirmation", booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={"booking_id": booking_id}).get("Item")
    return render_template("confirmation.html", booking=booking)

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(debug=True)
