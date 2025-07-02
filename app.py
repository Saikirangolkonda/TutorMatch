from flask import Flask, request, render_template, redirect, url_for, session, jsonify, abort
from datetime import datetime, timedelta
from decimal import Decimal
import boto3
import uuid
import json
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# AWS setup
region = 'ap-south-1'
dynamodb = boto3.resource('dynamodb', region_name=region)
sns = boto3.client('sns', region_name=region)

# DynamoDB Tables
users_table = dynamodb.Table('Users')
tutors_table = dynamodb.Table('Tutors')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')
sessions_table = dynamodb.Table('Sessions')

# SNS Topic ARN
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:336133425253:TutorMatchNotifications'

# Load tutor data from JSON
try:
    with open('templates/tutors_data.json') as f:
        tutor_data = json.load(f)
except FileNotFoundError:
    print("Warning: tutors_data.json not found. Using empty tutor list.")
    tutor_data = []

@app.route('/')
def home():
    return render_template('homepage.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        role = request.form.get('role', 'student')
        try:
            users_table.put_item(Item={
                'email': email,
                'password': password,
                'name': name,
                'role': role
            })
            return redirect(url_for('login'))
        except Exception as e:
            print("DynamoDB Register Error:", str(e))
            return "Error during registration"
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            response = users_table.get_item(Key={'email': email})
            user = response.get('Item')
            if user and user['password'] == password:
                session['user'] = user
                role = user.get('role', 'student')
                return redirect(url_for('student_dashboard' if role == 'student' else 'tutor_dashboard'))
            else:
                return "Invalid credentials", 401
        except Exception as e:
            print("Login Error:", str(e))
            return "Login failed"
    return render_template('login.html')

@app.route('/student-dashboard')
def student_dashboard():
    if 'user' not in session or session['user'].get('role') != 'student':
        return redirect(url_for('login'))
    return render_template('student_dashboard.html')

@app.route('/tutor-dashboard')
def tutor_dashboard():
    if 'user' not in session or session['user'].get('role') != 'tutor':
        return redirect(url_for('login'))
    return render_template('tutor_dashboard.html')

@app.route('/tutor-search')
def tutor_search():
    return render_template('tutor_search.html', tutors=tutor_data)

@app.route('/book-session/<int:tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    if 'user' not in session or session['user'].get('role') != 'student':
        return redirect(url_for('login'))

    # Convert tutor_id to int to match with tutor data
    try:
        tutor_id_int = int(tutor_id)
    except (ValueError, TypeError):
        print(f"Invalid tutor_id: {tutor_id}")
        abort(404)

    # Find tutor by ID
    tutor = None
    for t in tutor_data:
        if isinstance(t, dict) and t.get('id') == tutor_id_int:
            tutor = t
            break
    
    if not tutor:
        print(f"Tutor not found for ID: {tutor_id_int}")
        abort(404)

    if request.method == 'POST':
        try:
            session_format = request.form.get('session_format', 'Online')
            booking_id = str(uuid.uuid4())
            start_time = datetime.now() + timedelta(days=1)
            end_time = start_time + timedelta(hours=1)
            
            # Ensure price is properly handled
            price = tutor.get('price', 0)
            if isinstance(price, str):
                price = float(price.replace('₹', '').replace(',', '').strip())
            total_price = Decimal(str(price))

            bookings_table.put_item(Item={
                'booking_id': booking_id,
                'student_email': session['user']['email'],
                'tutor_id': str(tutor_id_int),
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'total_price': str(total_price),
                'session_format': session_format,
                'tutor_name': tutor.get('name', 'Unknown Tutor'),
                'status': 'pending_payment'
            })

            return redirect(url_for('payment', booking_id=booking_id))
        except Exception as e:
            print("Booking Error:", str(e))
            return f"Error while booking: {str(e)}"

    return render_template('booksession.html', tutor=tutor)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    if not booking_id:
        abort(400, description="Booking ID is required")
    
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            abort(404, description="Booking not found")
        return render_template('payment.html', booking=booking, booking_id=booking_id)
    except Exception as e:
        print("Payment Load Error:", str(e))
        return f"<h1>Payment Error</h1><p>{str(e)}</p>"

@app.route('/process-payment', methods=['POST'])
def process_payment():
    try:
        payment_id = str(uuid.uuid4())
        booking_id = request.form['booking_id']
        payment_method = request.form['payment_method']
        email = request.form['email']
        phone = request.form['phone']

        # Validate required fields
        if not all([booking_id, payment_method, email, phone]):
            return "Missing required payment information", 400

        payments_table.put_item(Item={
            'payment_id': payment_id,
            'booking_id': booking_id,
            'payment_method': payment_method,
            'email': email,
            'phone': phone,
            'status': 'Paid',
            'timestamp': datetime.now().isoformat()
        })

        # Get booking details
        booking_response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = booking_response.get('Item')
        
        if not booking:
            return "Booking not found", 404
            
        tutor_name = booking.get('tutor_name', 'your tutor')
        session_format = booking.get('session_format', 'Online')

        # Update booking status
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="SET #s = :s, payment_id = :p",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'confirmed', ':p': payment_id}
        )

        # Send SNS notification
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject="Session Confirmation",
                Message=f"Payment successful for your {session_format} session with {tutor_name}. Booking ID: {booking_id}"
            )
        except Exception as sns_error:
            print(f"SNS Error: {sns_error}")
            # Continue even if SNS fails

        return render_template("confirmation.html", booking_id=booking_id)
    except Exception as e:
        print("Payment Process Error:", str(e))
        return f"Payment failed: {str(e)}"

@app.route('/api/student-data')
def student_data():
    student_email = request.args.get('student_email')
    if not student_email:
        return jsonify([])
    
    try:
        response = bookings_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('student_email').eq(student_email)
        )
        return jsonify(response.get('Items', []))
    except Exception as e:
        print("Student Data Load Error:", str(e))
        return jsonify([])

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    if not booking_id:
        abort(400, description="Booking ID is required")
    
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            abort(404, description="Booking not found")
        return render_template('confirmation.html', booking=booking)
    except Exception as e:
        print("Confirmation Load Error:", str(e))
        return f"Confirmation error: {str(e)}"

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
