from flask import Flask, request, render_template_string, redirect, url_for, jsonify, abort
from datetime import datetime, timedelta
import json
import uuid
import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# AWS Configuration
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
DYNAMODB_TABLE_USERS = os.environ.get('DYNAMODB_TABLE_USERS', 'Users_Table')
DYNAMODB_TABLE_TUTORS = os.environ.get('DYNAMODB_TABLE_TUTORS', 'Tutors_Table')
DYNAMODB_TABLE_BOOKINGS = os.environ.get('DYNAMODB_TABLE_BOOKINGS', 'Bookings_Table')
DYNAMODB_TABLE_PAYMENTS = os.environ.get('DYNAMODB_TABLE_PAYMENTS', 'Payments_Table')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic')

# Initialize AWS clients
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    sns_client = boto3.client('sns', region_name=AWS_REGION)
    
    # DynamoDB tables
    users_table = dynamodb.Table(DYNAMODB_TABLE_USERS)
    tutors_table = dynamodb.Table(DYNAMODB_TABLE_TUTORS)
    bookings_table = dynamodb.Table(DYNAMODB_TABLE_BOOKINGS)
    payments_table = dynamodb.Table(DYNAMODB_TABLE_PAYMENTS)
    
    logger.info("AWS services initialized successfully")
except Exception as e:
    logger.error(f"Error initializing AWS services: {e}")
    raise

# Initialize default tutors data
def initialize_tutors_data():
    """Initialize default tutors in DynamoDB if they don't exist"""
    try:
        default_tutors = [
            {
                "tutor_id": "tutor1",
                "name": "John Smith",
                "subjects": ["Mathematics", "Physics"],
                "rate": 30,
                "rating": 4.8,
                "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
                "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"],
                "active": True,
                "created_at": datetime.now().isoformat()
            },
            {
                "tutor_id": "tutor2",
                "name": "Sarah Johnson",
                "subjects": ["English", "Literature"],
                "rate": 25,
                "rating": 4.6,
                "bio": "English literature specialist, helping students excel in writing and analysis.",
                "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"],
                "active": True,
                "created_at": datetime.now().isoformat()
            }
        ]
        
        for tutor in default_tutors:
            try:
                tutors_table.put_item(
                    Item=tutor,
                    ConditionExpression='attribute_not_exists(tutor_id)'
                )
                logger.info(f"Added default tutor: {tutor['name']}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    logger.info(f"Tutor {tutor['name']} already exists")
                else:
                    logger.error(f"Error adding tutor {tutor['name']}: {e}")
    except Exception as e:
        logger.error(f"Error initializing tutors data: {e}")

# Initialize tutors on startup
initialize_tutors_data()

# Helper functions for DynamoDB operations
def get_all_tutors():
    """Get all active tutors from DynamoDB"""
    try:
        response = tutors_table.scan(
            FilterExpression=Attr('active').eq(True)
        )
        return response.get('Items', [])
    except Exception as e:
        logger.error(f"Error getting tutors: {e}")
        return []

def get_tutor_by_id(tutor_id):
    """Get a specific tutor by ID"""
    try:
        response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        return response.get('Item')
    except Exception as e:
        logger.error(f"Error getting tutor {tutor_id}: {e}")
        return None

def create_user(email, password, name, role="student"):
    """Create a new user in DynamoDB"""
    try:
        user_data = {
            "email": email,
            "password": password,  # In production, hash this!
            "name": name,
            "role": role,
            "created_at": datetime.now().isoformat()
        }
        users_table.put_item(Item=user_data)
        return True
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return False

def get_user_by_email(email):
    """Get user by email"""
    try:
        response = users_table.get_item(Key={'email': email})
        return response.get('Item')
    except Exception as e:
        logger.error(f"Error getting user {email}: {e}")
        return None

def create_booking(booking_data):
    """Create a new booking in DynamoDB"""
    try:
        bookings_table.put_item(Item=booking_data)
        return True
    except Exception as e:
        logger.error(f"Error creating booking: {e}")
        return False

def get_booking_by_id(booking_id):
    """Get booking by ID"""
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        return response.get('Item')
    except Exception as e:
        logger.error(f"Error getting booking {booking_id}: {e}")
        return None

def update_booking_status(booking_id, status, payment_id=None):
    """Update booking status"""
    try:
        update_expression = "SET #status = :status, updated_at = :updated_at"
        expression_values = {
            ':status': status,
            ':updated_at': datetime.now().isoformat()
        }
        expression_names = {'#status': 'status'}
        
        if payment_id:
            update_expression += ", payment_id = :payment_id"
            expression_values[':payment_id'] = payment_id
        
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
            ExpressionAttributeNames=expression_names
        )
        return True
    except Exception as e:
        logger.error(f"Error updating booking {booking_id}: {e}")
        return False

def create_payment(payment_data):
    """Create a new payment record"""
    try:
        payments_table.put_item(Item=payment_data)
        return True
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        return False

def get_student_bookings():
    """Get all bookings for display"""
    try:
        response = bookings_table.scan()
        return response.get('Items', [])
    except Exception as e:
        logger.error(f"Error getting student bookings: {e}")
        return []

def get_student_payments():
    """Get all payments for display"""
    try:
        response = payments_table.scan()
        return response.get('Items', [])
    except Exception as e:
        logger.error(f"Error getting student payments: {e}")
        return []

def send_notification_email(email, subject, message):
    """Send notification via SNS"""
    try:
        # Create the message
        sns_message = {
            "default": message,
            "email": f"Subject: {subject}\n\n{message}"
        }
        
        # Publish to SNS topic
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(sns_message),
            MessageStructure='json',
            Subject=subject
        )
        
        logger.info(f"Notification sent successfully. MessageId: {response['MessageId']}")
        return True
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        return False

def send_booking_confirmation_notification(booking, email):
    """Send booking confirmation and upcoming session notification"""
    try:
        tutor_name = booking.get('tutor_name', 'Unknown Tutor')
        subject_name = booking.get('subject', 'Unknown Subject')
        session_date = booking.get('date', 'Unknown Date')
        session_time = booking.get('time', 'Unknown Time')
        total_price = booking.get('total_price', 0)
        session_format = booking.get('session_format', 'Online')
        
        # Create combined notification message
        subject = f"TutorMatch: Session Confirmed & Payment Received - {subject_name}"
        
        message = f"""
Dear Student,

Great news! Your tutoring session has been confirmed and payment has been processed successfully.

SESSION DETAILS:
📚 Subject: {subject_name}
👨‍🏫 Tutor: {tutor_name}
📅 Date: {session_date}
🕐 Time: {session_time}
💻 Format: {session_format}
💰 Amount Paid: ${total_price}

UPCOMING SESSION REMINDER:
Your session is scheduled for {session_date} at {session_time}. Please make sure to:
- Be ready 5 minutes before the session starts
- Have all necessary materials prepared
- Ensure stable internet connection (for online sessions)
- Check your email for any updates from your tutor

If you need to reschedule or have any questions, please contact us immediately.

Thank you for choosing TutorMatch!

Best regards,
TutorMatch Team
"""
        
        return send_notification_email(email, subject, message)
    except Exception as e:
        logger.error(f"Error sending booking confirmation notification: {e}")
        return False

# Homepage route
@app.route("/")
def homepage():
    try:
        # Try to render template if it exists
        with open("templates/homepage.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception:
        # Fallback if template doesn't exist
        return '''
        <html>
            <head><title>TutorMatch</title></head>
            <body>
                <h1>Welcome to TutorMatch</h1>
                <p>Connect with experienced tutors!</p>
                <a href="/login">Login</a> | <a href="/register">Get Started</a> | <a href="/login">Browse Tutors</a> | <a href="/register">Join as Student</a>
            </body>
        </html>
        '''

# Button redirect routes
@app.route("/get-started")
def get_started():
    return redirect(url_for('register_page'))

@app.route("/browse-tutors")
def browse_tutors():
    return redirect(url_for('login_page'))

@app.route("/join-as-student")
def join_as_student():
    return redirect(url_for('register_page'))

# Authentication routes
@app.route("/login", methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = get_user_by_email(email)
        if user and user.get("password") == password:
            return redirect(url_for('student_dashboard'))
        else:
            abort(401)
    
    try:
        with open("templates/login.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception:
        return '''
        <html>
            <head><title>Login - TutorMatch</title></head>
            <body>
                <h1>Student Login</h1>
                <form method="post" action="/login">
                    <p>
                        <label>Email:</label><br>
                        <input type="email" name="email" required>
                    </p>
                    <p>
                        <label>Password:</label><br>
                        <input type="password" name="password" required>
                    </p>
                    <button type="submit">Login</button>
                </form>
                <p><a href="/register">Don't have an account? Register</a></p>
            </body>
        </html>
        '''

@app.route("/register", methods=['GET', 'POST'])
def register_page():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        
        existing_user = get_user_by_email(email)
        if not existing_user:
            if create_user(email, password, name):
                return redirect(url_for('login_page'))
            else:
                abort(500)
        else:
            abort(400)
    
    try:
        with open("templates/register.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception:
        return '''
        <html>
            <head><title>Register - TutorMatch</title></head>
            <body>
                <h1>Student Registration</h1>
                <form method="post" action="/register">
                    <p>
                        <label>Name:</label><br>
                        <input type="text" name="name" required>
                    </p>
                    <p>
                        <label>Email:</label><br>
                        <input type="email" name="email" required>
                    </p>
                    <p>
                        <label>Password:</label><br>
                        <input type="password" name="password" required>
                    </p>
                    <button type="submit">Register</button>
                </form>
                <p><a href="/login">Already have an account? Login</a></p>
            </body>
        </html>
        '''

# Dashboard and main application routes
@app.route("/student-dashboard")
def student_dashboard():
    try:
        with open("templates/student_dashboard.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception:
        return '''
        <html>
            <head><title>Student Dashboard - TutorMatch</title></head>
            <body>
                <h1>Student Dashboard</h1>
                <p>Welcome to your dashboard!</p>
                <ul>
                    <li><a href="/tutor-search">Search for Tutors</a></li>
                    <li><a href="/api/student-data">View My Bookings (JSON)</a></li>
                    <li><a href="/logout">Logout</a></li>
                </ul>
            </body>
        </html>
        '''

@app.route("/tutor-search")
def tutor_search():
    tutors_data = get_all_tutors()
    
    try:
        with open("templates/tutor_search.html", 'r') as f:
            template_content = f.read()
        tutors_with_id = [{"id": tutor.get("tutor_id"), **tutor} for tutor in tutors_data]
        return render_template_string(template_content, tutors_with_id=tutors_with_id)
    except Exception:
        # Fallback HTML with tutor list
        tutors_html = ""
        for tutor in tutors_data:
            tutor_id = tutor.get('tutor_id')
            tutors_html += f'''
            <div style="border: 1px solid #ccc; padding: 10px; margin: 10px 0;">
                <h3>{tutor.get('name', 'Unknown')}</h3>
                <p>Subjects: {', '.join(tutor.get('subjects', []))}</p>
                <p>Rate: ${tutor.get('rate', 25)}/hour</p>
                <p>Rating: {tutor.get('rating', 4.5)}/5</p>
                <p>{tutor.get('bio', 'No bio available')}</p>
                <a href="/tutor-profile/{tutor_id}">View Profile</a>
            </div>
            '''
        
        return f'''
        <html>
            <head><title>Find Tutors - TutorMatch</title></head>
            <body>
                <h1>Find Tutors</h1>
                <div>{tutors_html}</div>
                <p><a href="/student-dashboard">Back to Dashboard</a></p>
            </body>
        </html>
        '''

# Tutor profile and booking routes
@app.route("/tutor-profile/<tutor_id>")
def tutor_profile(tutor_id):
    tutor = get_tutor_by_id(tutor_id)
    if not tutor:
        abort(404)
    
    try:
        with open("templates/tutor_profile.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content, tutor=tutor, tutor_id=tutor_id)
    except Exception:
        subjects_options = ''.join([f'<option value="{subject}">{subject}</option>' for subject in tutor.get('subjects', ['General'])])
        
        return f'''
        <html>
            <head><title>{tutor.get('name', 'Unknown')} - TutorMatch</title></head>
            <body>
                <h1>{tutor.get('name', 'Unknown')}</h1>
                <p><strong>Subjects:</strong> {', '.join(tutor.get('subjects', []))}</p>
                <p><strong>Rate:</strong> ${tutor.get('rate', 25)}/hour</p>
                <p><strong>Rating:</strong> {tutor.get('rating', 4.5)}/5</p>
                <p><strong>Bio:</strong> {tutor.get('bio', 'No bio available')}</p>
                <p><strong>Availability:</strong> {', '.join(tutor.get('availability', ['Contact for availability']))}</p>
                
                <h2>Book a Session</h2>
                <form method="post" action="/book-session/{tutor_id}">
                    <p>
                        <label>Date:</label><br>
                        <input type="date" name="date" required>
                    </p>
                    <p>
                        <label>Time:</label><br>
                        <input type="time" name="time" required>
                    </p>
                    <p>
                        <label>Subject:</label><br>
                        <select name="subject" required>
                            {subjects_options}
                        </select>
                    </p>
                    <p>
                        <label>Session Type:</label><br>
                        <select name="session_type">
                            <option value="Single Session">Single Session</option>
                            <option value="Weekly">Weekly</option>
                            <option value="Monthly">Monthly</option>
                        </select>
                    </p>
                    <p>
                        <label>Number of Sessions:</label><br>
                        <input type="number" name="sessions_count" value="1" min="1">
                    </p>
                    <p>
                        <label>Learning Goals:</label><br>
                        <textarea name="learning_goals" rows="3"></textarea>
                    </p>
                    <p>
                        <label>Session Format:</label><br>
                        <select name="session_format">
                            <option value="Online Video Call">Online Video Call</option>
                            <option value="In Person">In Person</option>
                        </select>
                    </p>
                    <p>
                        <label>Email (for notifications):</label><br>
                        <input type="email" name="student_email" required>
                    </p>
                    <button type="submit">Book Session</button>
                </form>
                
                <p><a href="/tutor-search">Back to Search</a></p>
            </body>
        </html>
        '''

@app.route("/book-session/<tutor_id>", methods=['GET', 'POST'])
def book_session_page(tutor_id):
    tutor = get_tutor_by_id(tutor_id)
    if not tutor:
        abort(404)

    if request.method == 'POST':
        return book_session_from_profile(tutor_id)

    try:
        with open("templates/booksession.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content, tutor=tutor, tutor_id=tutor_id)
    except Exception:
        return redirect(url_for('tutor_profile', tutor_id=tutor_id))

def book_session_from_profile(tutor_id):
    tutor = get_tutor_by_id(tutor_id)
    if not tutor:
        abort(404)

    date = request.form.get('date')
    time = request.form.get('time')
    subject = request.form.get('subject')
    session_type = request.form.get('session_type', 'Single Session')
    sessions_count = int(request.form.get('sessions_count', 1))
    learning_goals = request.form.get('learning_goals', '')
    session_format = request.form.get('session_format', 'Online Video Call')
    student_email = request.form.get('student_email', '')

    booking_id = str(uuid.uuid4())
    calculated_price = tutor.get('rate', 25) * sessions_count

    booking = {
        "booking_id": booking_id,
        "tutor_id": tutor_id,
        "tutor_name": tutor.get('name', 'Unknown'),
        "tutor_rate": tutor.get('rate', 25),
        "date": date,
        "time": time,
        "subject": subject,
        "session_type": session_type,
        "sessions_count": sessions_count,
        "total_price": calculated_price,
        "learning_goals": learning_goals,
        "session_format": session_format,
        "student_email": student_email,
        "status": "pending_payment",
        "created_at": datetime.now().isoformat()
    }

    if create_booking(booking):
        return redirect(url_for('payment_page', booking_id=booking_id))
    else:
        abort(500)

# Payment processing routes
@app.route("/payment")
def payment_page():
    booking_id = request.args.get('booking_id', '')
    if not booking_id:
        abort(404)
    
    booking = get_booking_by_id(booking_id)
    if not booking:
        abort(404)
    
    try:
        with open("templates/payment.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content, booking=booking, booking_id=booking_id)
    except Exception:
        return f'''
        <html>
            <head><title>Payment - TutorMatch</title></head>
            <body>
                <h1>Payment</h1>
                <h2>Booking Summary</h2>
                <p><strong>Tutor:</strong> {booking.get('tutor_name', 'Unknown')}</p>
                <p><strong>Subject:</strong> {booking.get('subject', 'Unknown')}</p>
                <p><strong>Date:</strong> {booking.get('date', 'Unknown')}</p>
                <p><strong>Time:</strong> {booking.get('time', 'Unknown')}</p>
                <p><strong>Sessions:</strong> {booking.get('sessions_count', 1)}</p>
                <p><strong>Total:</strong> ${booking.get('total_price', 0)}</p>
                
                <h2>Payment Details</h2>
                <form method="post" action="/process-payment">
                    <input type="hidden" name="booking_id" value="{booking_id}">
                    <p>
                        <label>Payment Method:</label><br>
                        <select name="payment_method" required>
                            <option value="credit_card">Credit Card</option>
                            <option value="debit_card">Debit Card</option>
                            <option value="paypal">PayPal</option>
                        </select>
                    </p>
                    <p>
                        <label>Card Number:</label><br>
                        <input type="text" name="card_number" placeholder="1234 5678 9012 3456">
                    </p>
                    <p>
                        <label>Cardholder Name:</label><br>
                        <input type="text" name="cardholder_name">
                    </p>
                    <p>
                        <label>Email:</label><br>
                        <input type="email" name="email" value="{booking.get('student_email', '')}" required>
                    </p>
                    <p>
                        <label>Phone:</label><br>
                        <input type="tel" name="phone" required>
                    </p>
                    <button type="submit">Process Payment</button>
                </form>
            </body>
        </html>
        '''

@app.route("/process-payment", methods=['POST'])
def process_payment():
    booking_id = request.form.get('booking_id')
    payment_method = request.form.get('payment_method')
    card_number = request.form.get('card_number', '')
    cardholder_name = request.form.get('cardholder_name', '')
    email = request.form.get('email')
    phone = request.form.get('phone')
    
    booking = get_booking_by_id(booking_id)
    if not booking:
        abort(404)
    
    # Process payment (mock)
    payment_id = str(uuid.uuid4())
    payment_data = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking.get("total_price", 0),
        "payment_method": payment_method,
        "cardholder_name": cardholder_name,
        "customer_email": email,
        "customer_phone": phone,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }
    
    # Save payment and update booking
    if create_payment(payment_data) and update_booking_status(booking_id, "confirmed", payment_id):
        # Send notification email
        updated_booking = get_booking_by_id(booking_id)
        if updated_booking:
            send_booking_confirmation_notification(updated_booking, email)
        
        return redirect(url_for('confirmation_page', booking_id=booking_id))
    else:
        abort(500)

@app.route("/confirmation")
def confirmation_page():
    booking_id = request.args.get('booking_id', '')
    if not booking_id:
        abort(404)
    
    booking = get_booking_by_id(booking_id)
    if not booking:
        abort(404)
    
    try:
        with open("templates/confirmation.html", 'r') as f:
            template_content = f.read()
        return render_template_string(template_content, booking=booking)
    except Exception:
        return f'''
        <html>
            <head><title>Booking Confirmed - TutorMatch</title></head>
            <body>
                <h1>Booking Confirmed!</h1>
                <p>Your session has been successfully booked and notification sent to your email.</p>
                
                <h2>Booking Details</h2>
                <p><strong>Booking ID:</strong> {booking.get('booking_id', 'Unknown')}</p>
                <p><strong>Tutor:</strong> {booking.get('tutor_name', 'Unknown')}</p>
                <p><strong>Subject:</strong> {booking.get('subject', 'Unknown')}</p>
                <p><strong>Date:</strong> {booking.get('date', 'Unknown')}</p>
                <p><strong>Time:</strong> {booking.get('time', 'Unknown')}</p>
                <p><strong>Format:</strong> {booking.get('session_format', 'Unknown')}</p>
                <p><strong>Total Paid:</strong> ${booking.get('total_price', 0)}</p>
                
                <p><a href="/student-dashboard">Back to Dashboard</a></p>
            </body>
        </html>
        '''

# API endpoints
@app.route("/api/student-data")
def get_student_data():
    """Get student's bookings, payments, and notifications"""
    
    student_email = request.args.get('student_email', '')
    
    # Get bookings from DynamoDB
    all_bookings = get_student_bookings()
    all_payments = get_student_payments()
    
    student_bookings = []
    student_payments = []
    notifications = []
    
    # Process bookings
    for booking in all_bookings:
        student_bookings.append({
            "id": booking.get("booking_id"),
            "tutor_name": booking.get("tutor_name"),
            "subject": booking.get("subject"),
            "date": booking.get("date"),
            "time": booking.get("time"),
            "status": booking.get("status"),
            "total_price": booking.get("total_price"),
            "session_format": booking.get("session_format"),
            "created_at": booking.get("created_at")
        })
        
        # Add notifications based on booking status
        if booking.get("status") == "confirmed":
            booking_date = booking.get("created_at", "")
            try:
                created_date = datetime.fromisoformat(booking_date.replace('Z', '+00:00') if 'Z' in booking_date else booking_date)
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your {booking.get('subject', 'Unknown')} session with {booking.get('tutor_name', 'Unknown')} is confirmed for {booking.get('date', 'Unknown')}.",
                    "date": created_date.strftime("%B %d, %Y")
                })
                
                # Check for upcoming sessions
                try:
                    session_datetime = datetime.strptime(f"{booking.get('date', '')} {booking.get('time', '')}", "%Y-%m-%d %H:%M")
                    if session_datetime > datetime.now() and session_datetime < datetime.now() + timedelta(days=1):
                        notifications.append({
                            "type": "reminder",
                            "title": "Session Reminder",
                            "message": f"You have a {booking.get('subject', 'Unknown')} session tomorrow at {booking.get('time', 'Unknown')}.",
                            "date": datetime.now().strftime("%B %d, %Y")
                        })
                except ValueError:
                    pass  # Invalid date/time format
            except (ValueError, AttributeError):
                pass
    
    # Process payments
    for payment in all_payments:
        # Find corresponding booking
        booking = next((b for b in all_bookings if b.get("booking_id") == payment.get("booking_id")), {})
        student_payments.append({
            "id": payment.get("payment_id"),
            "tutor_name": booking.get("tutor_name", "Unknown"),
            "amount": payment.get("amount"),
            "status": payment.get("status"),
            "date": payment.get("created_at"),
            "method": payment.get("payment_method")
        })
    
    # Sort data
    student_bookings.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    student_payments.sort(key=lambda x: x.get("date", ""), reverse=True)
    notifications.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    return jsonify({
        "bookings": student_bookings,
        "payments": student_payments,
        "notifications": notifications
    })

# Utility routes
@app.route("/logout")
def logout():
    return redirect(url_for('homepage'))

# Health check endpoint
@app.route("/health")
def health_check():
    try:
        # Check DynamoDB connectivity
        tutors_count = len(get_all_tutors())
        
        # Check SNS connectivity
        sns_client.get_topic_attributes(TopicArn=SNS_TOPIC_ARN)
        
        return jsonify({
            "status": "healthy", 
            "tutors_count": tutors_count,
            "aws_services": "connected",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy", 
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(401)
def unauthorized(error):
    return jsonify({"error": "Unauthorized access"}), 401

@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8000)), debug=False)
