# TutorMatch AWS-Compatible Flask App with DynamoDB and SNS Integration

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
import json
import os
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal
from datetime import datetime
import uuid

app = Flask(__name__)
app.secret_key = 'your_secret_key_change_in_production'

# AWS Configuration
AWS_REGION = 'ap-south-1'
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
sns = boto3.client('sns', region_name=AWS_REGION)

# Table references
users_table = dynamodb.Table('Users')
tutors_table = dynamodb.Table('Tutors')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')

@app.route('/')
def home():
    return render_template('homepage.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']

        try:
            users_table.put_item(
                Item={
                    'email': email,
                    'password': password,
                    'name': name
                },
                ConditionExpression='attribute_not_exists(email)'
            )
            flash('Registration successful! Please log in.')
            return redirect(url_for('login'))
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                flash('User already exists.')
            else:
                flash('Registration failed.')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        response = users_table.get_item(Key={'email': email})
        user = response.get('Item')

        if user and user.get('password') == password:
            session['email'] = email
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid credentials.')

    return render_template('login.html')

@app.route('/student-dashboard')
def student_dashboard():
    if 'email' not in session:
        return redirect(url_for('login'))
    return render_template('student_dashboard.html')

@app.route('/tutor-search')
def tutor_search():
    tutors = tutors_table.scan().get('Items', [])
    return render_template('tutor_search.html', tutors=tutors)

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    tutor = tutors_table.get_item(Key={'tutor_id': tutor_id}).get('Item')
    if not tutor:
        abort(404)
    return render_template('tutor_profile.html', tutor=tutor)

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    tutor = tutors_table.get_item(Key={'tutor_id': tutor_id}).get('Item')
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

        bookings_table.put_item(Item={
            'booking_id': booking_id,
            'email': session.get('email'),
            'tutor_id': tutor_id,
            'date': date,
            'time': time,
            'subject': subject,
            'session_type': session_type,
            'sessions_count': sessions_count,
            'total_price': Decimal(str(total_price)),
            'learning_goals': learning_goals,
            'session_format': session_format,
            'status': 'pending_payment',
            'created_at': datetime.now().isoformat()
        })

        return redirect(url_for('payment', booking_id=booking_id))

    return render_template('booksession.html', tutor=tutor)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return render_template('payment.html', booking=booking)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form['payment_method']
    email = request.form['email']
    phone = request.form['phone']

    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)

    payment_id = str(uuid.uuid4())
    total_amount = booking['total_price']

    payments_table.put_item(Item={
        'payment_id': payment_id,
        'booking_id': booking_id,
        'amount': Decimal(str(total_amount)),
        'payment_method': payment_method,
        'status': 'completed',
        'created_at': datetime.now().isoformat()
    })

    bookings_table.update_item(
        Key={'booking_id': booking_id},
        UpdateExpression="SET #s = :s, payment_id = :pid",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "confirmed", ":pid": payment_id}
    )

    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="TutorMatch Booking Confirmed",
            Message=f"Booking confirmed with tutor ID: {booking['tutor_id']} for {booking['date']} at {booking['time']}."
        )
    except Exception as e:
        print("SNS Notification Failed:", e)

    return redirect(url_for('confirmation', booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return render_template('confirmation.html', booking=booking)

@app.route('/api/student-data')
def api_student_data():
    student_email = request.args.get('student_email')
    if not student_email:
        return jsonify({'error': 'Missing student_email'}), 400

    user = users_table.get_item(Key={'email': student_email}).get('Item')
    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'user': user})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
