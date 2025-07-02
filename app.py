# TutorMatch AWS-Compatible Flask App with DynamoDB and SNS Integration

from flask import Flask, request, render_template_string, redirect, url_for, jsonify, abort
from datetime import datetime, timedelta
import boto3
import uuid
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change in production

# AWS Configuration
region_name = 'ap-south-1'
dynamodb = boto3.resource('dynamodb', region_name=region_name)
sns = boto3.client('sns', region_name=region_name)

# DynamoDB Tables
tables = {
    'users': dynamodb.Table('Users'),
    'tutors': dynamodb.Table('Tutors'),
    'bookings': dynamodb.Table('Bookings'),
    'payments': dynamodb.Table('Payments')
}

# SNS Topic ARN
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

@app.route('/')
def homepage():
    return '''<h1>Welcome to TutorMatch</h1>
              <a href="/login">Login</a> |
              <a href="/register">Register</a> |
              <a href="/tutor-search">Browse Tutors</a>'''

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        try:
            tables['users'].put_item(Item={
                'email': email,
                'password': password,
                'name': name,
                'role': 'student'
            })
            return redirect(url_for('login'))
        except Exception as e:
            return str(e), 500
    return '''<form method="post">
                Name: <input name="name"><br>
                Email: <input name="email"><br>
                Password: <input name="password"><br>
                <button type="submit">Register</button>
              </form>'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            response = tables['users'].get_item(Key={'email': email})
            user = response.get('Item')
            if user and user['password'] == password:
                return redirect(url_for('dashboard', email=email))
            else:
                return 'Invalid credentials', 401
        except Exception as e:
            return str(e), 500
    return '''<form method="post">
                Email: <input name="email"><br>
                Password: <input name="password"><br>
                <button type="submit">Login</button>
              </form>'''

@app.route('/dashboard')
def dashboard():
    return '''<h2>Dashboard</h2>
              <a href="/tutor-search">Search Tutors</a>'''

@app.route('/tutor-search')
def tutor_search():
    try:
        response = tables['tutors'].scan()
        tutors = response.get('Items', [])
        html = '<h2>Available Tutors</h2>'
        for tutor in tutors:
            html += f'''<div>
                        <h3>{tutor['name']}</h3>
                        Subjects: {', '.join(tutor.get('subjects', []))}<br>
                        <a href="/tutor/{tutor['tutor_id']}">View Profile</a>
                      </div>'''
        return html
    except Exception as e:
        return str(e), 500

@app.route('/tutor/<tutor_id>', methods=['GET', 'POST'])
def tutor_profile(tutor_id):
    try:
        response = tables['tutors'].get_item(Key={'tutor_id': tutor_id})
        tutor = response.get('Item')
        if not tutor:
            return 'Tutor not found', 404

        if request.method == 'POST':
            date = request.form['date']
            time = request.form['time']
            subject = request.form['subject']
            email = request.form['email']  # Get student email
            booking_id = str(uuid.uuid4())
            rate = int(tutor.get('rate', 25))
            booking_item = {
                'booking_id': booking_id,
                'tutor_id': tutor_id,
                'student_email': email,
                'date': date,
                'time': time,
                'subject': subject,
                'status': 'pending_payment',
                'total_price': rate,
                'created_at': datetime.now().isoformat()
            }
            tables['bookings'].put_item(Item=booking_item)

            # Send notification
            notify_upcoming_session(email, tutor['name'], subject, date, time, rate)

            return redirect(url_for('payment', booking_id=booking_id))

        return f'''<h2>{tutor['name']}</h2>
                  Subjects: {', '.join(tutor.get('subjects', []))}<br>
                  <form method="post">
                    Email: <input name="email" required><br>
                    Date: <input type="date" name="date"><br>
                    Time: <input type="time" name="time"><br>
                    Subject: <select name="subject">
                        {''.join([f'<option value="{s}">{s}</option>' for s in tutor.get('subjects', [])])}
                    </select><br>
                    <button type="submit">Book</button>
                  </form>'''
    except Exception as e:
        return str(e), 500

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    try:
        response = tables['bookings'].get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            return 'Booking not found', 404
        return f'''<h2>Payment for Booking {booking_id}</h2>
                  Amount: ${booking['total_price']}<br>
                  <form method="post" action="/process-payment">
                    <input type="hidden" name="booking_id" value="{booking_id}">
                    Payment Method: <input name="payment_method"><br>
                    Email: <input name="email"><br>
                    Phone: <input name="phone"><br>
                    <button type="submit">Pay</button>
                  </form>'''
    except Exception as e:
        return str(e), 500

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    email = request.form['email']
    phone = request.form['phone']
    method = request.form['payment_method']
    payment_id = str(uuid.uuid4())
    try:
        # Update booking
        tables['bookings'].update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="set #st=:s",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":s": "confirmed"}
        )

        # Record payment
        response = tables['bookings'].get_item(Key={'booking_id': booking_id})
        booking = response['Item']
        tables['payments'].put_item(Item={
            'payment_id': payment_id,
            'booking_id': booking_id,
            'email': email,
            'phone': phone,
            'payment_method': method,
            'amount': booking['total_price'],
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        })

        return redirect(url_for('confirmation', booking_id=booking_id))
    except Exception as e:
        return str(e), 500

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    return f'<h2>Booking Confirmed!</h2><p>Booking ID: {booking_id}</p>'

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/api/student-data')
def api_student_data():
    student_email = request.args.get('student_email')
    if not student_email:
        return jsonify({'error': 'Missing student_email'}), 400
    response = tables['users'].get_item(Key={'email': student_email})
    user = response.get('Item')
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'user': user})

def notify_upcoming_session(email, tutor_name, subject, date, time, price):
    message = f"Your session for {subject} with {tutor_name} is scheduled on {date} at {time}.\nTotal Fee: ${price}."
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject="Upcoming Tutor Session Notification",
            MessageAttributes={
                'email': {
                    'DataType': 'String',
                    'StringValue': email
                }
            }
        )
    except Exception as e:
        print("SNS Error:", e)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
