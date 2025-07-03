from flask import Flask, render_template, request, redirect, url_for, jsonify, abort, session, flash
from datetime import datetime, timedelta
import os, json, uuid, logging
import boto3
from werkzeug.security import generate_password_hash, check_password_hash
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load environment variables
load_dotenv()

# ---------------------------------------
# Flask App Initialization
# ---------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'tutormatch_secret_key_2024')

# ---------------------------------------
# App Configuration
# ---------------------------------------
AWS_REGION_NAME = os.environ.get('AWS_REGION_NAME', 'ap-south-1')

# Email Configuration
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
ENABLE_EMAIL = os.environ.get('ENABLE_EMAIL', 'False').lower() == 'true'

# Table Names
USERS_TABLE_NAME = os.environ.get('USERS_TABLE_NAME', 'Users')
TUTORS_TABLE_NAME = os.environ.get('TUTORS_TABLE_NAME', 'Tutors')
BOOKINGS_TABLE_NAME = os.environ.get('BOOKINGS_TABLE_NAME', 'Bookings')
PAYMENTS_TABLE_NAME = os.environ.get('PAYMENTS_TABLE_NAME', 'Payments')
SESSIONS_TABLE_NAME = os.environ.get('SESSIONS_TABLE_NAME', 'Sessions')

# SNS Configuration
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications')
ENABLE_SNS = os.environ.get('ENABLE_SNS', 'True').lower() == 'true'

# ---------------------------------------
# AWS Resources
# ---------------------------------------
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION_NAME)
sns = boto3.client('sns', region_name=AWS_REGION_NAME)

# DynamoDB Tables
users_table = dynamodb.Table(USERS_TABLE_NAME)
tutors_table = dynamodb.Table(TUTORS_TABLE_NAME)
bookings_table = dynamodb.Table(BOOKINGS_TABLE_NAME)
payments_table = dynamodb.Table(PAYMENTS_TABLE_NAME)
sessions_table = dynamodb.Table(SESSIONS_TABLE_NAME)

# ---------------------------------------
# Logging
# ---------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tutormatch.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------------------
# Helper Functions for Data Type Conversion
# ---------------------------------------
def safe_decimal_to_float(value):
    """Safely convert Decimal to float, handling None and invalid values"""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return 0.0

def safe_to_decimal(value):
    """Safely convert value to Decimal for DynamoDB storage"""
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return Decimal('0')

def safe_to_int(value):
    """Safely convert value to int"""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0

# ---------------------------------------
# Helper Functions
# ---------------------------------------
def is_logged_in():
    return 'email' in session

def get_user_role(email):
    try:
        response = users_table.get_item(Key={'email': email})
        return response.get('Item', {}).get('role', 'student')
    except Exception as e:
        logger.error(f"Error fetching role: {e}")
    return 'student'

def send_email(to_email, subject, body):
    if not ENABLE_EMAIL:
        logger.info(f"[Email Skipped] Subject: {subject} to {to_email}")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()

        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")

def publish_to_sns(message, subject="TutorMatch Notification"):
    if not ENABLE_SNS:
        logger.info("[SNS Skipped] Message: {}".format(message))
        return

    try:
        response = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject
        )
        logger.info(f"SNS published: {response['MessageId']}")
    except Exception as e:
        logger.error(f"SNS publish failed: {e}")

def initialize_tutors_data():
    """Initialize tutors table with default data if empty"""
    try:
        # Check if tutors table has data
        response = tutors_table.scan(Limit=1)
        if not response.get('Items'):
            # Initialize with default tutors
            default_tutors = {
                "tutor1": {
                    "tutor_id": "tutor1",
                    "name": "John Smith",
                    "email": "john.smith@example.com",
                    "subjects": ["Mathematics", "Physics"],
                    "rate": safe_to_decimal(30),
                    "rating": safe_to_decimal(4.8),
                    "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
                    "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"],
                    "status": "active",
                    "created_at": datetime.now().isoformat()
                },
                "tutor2": {
                    "tutor_id": "tutor2",
                    "name": "Sarah Johnson",
                    "email": "sarah.johnson@example.com",
                    "subjects": ["English", "Literature"],
                    "rate": safe_to_decimal(25),
                    "rating": safe_to_decimal(4.6),
                    "bio": "English literature specialist, helping students excel in writing and analysis.",
                    "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"],
                    "status": "active",
                    "created_at": datetime.now().isoformat()
                }
            }
            
            for tutor_data in default_tutors.values():
                tutors_table.put_item(Item=tutor_data)
                
            logger.info("Initialized tutors table with default data")
    except Exception as e:
        logger.error(f"Error initializing tutors data: {e}")

# Initialize tutors data on startup
initialize_tutors_data()

# ---------------------------------------
# Template Context Processors
# ---------------------------------------
@app.context_processor
def inject_now():
    """Inject current date/time into all templates"""
    return {
        'now': datetime.now(),
        'today': datetime.now().strftime('%Y-%m-%d'),
        'current_year': datetime.now().year
    }

# ---------------------------------------
# Routes
# ---------------------------------------

@app.route('/')
def homepage():
    try:
        return render_template("homepage.html")
    except Exception as e:
        logger.error(f"Template error: {e}")
        return """
        <h1>Welcome to TutorMatch</h1>
        <p>Find the perfect tutor for your learning needs!</p>
        <a href='/login'>Login</a> | <a href='/register'>Register</a> | <a href='/tutor-search'>Browse Tutors</a>
        """

@app.route('/register', methods=['GET', 'POST'])
def register():
    if is_logged_in():
        return redirect(url_for('student_dashboard'))
    
    if request.method == 'POST':
        # Form validation
        required_fields = ['name', 'email', 'password']
        for field in required_fields:
            if field not in request.form or not request.form[field]:
                flash(f'Please fill in the {field} field', 'danger')
                return render_template('register.html')
        
        # Check if passwords match
        if request.form['password'] != request.form.get('confirm_password', ''):
            flash('Passwords do not match', 'danger')
            return render_template('register.html')
        
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        role = request.form.get('role', 'student')  # Default to student
        phone = request.form.get('phone', '')
        
        # Check if user already exists
        try:
            existing_user = users_table.get_item(Key={'email': email}).get('Item')
            if existing_user:
                flash('Email already registered', 'danger')
                return render_template('register.html')
        except Exception as e:
            logger.error(f"Error checking existing user: {e}")
            flash('Registration error. Please try again.', 'danger')
            return render_template('register.html')

        # Add user to DynamoDB
        user_item = {
            'email': email,
            'name': name,
            'password': password,
            'role': role,
            'phone': phone,
            'status': 'active',
            'created_at': datetime.now().isoformat(),
        }
        
        try:
            users_table.put_item(Item=user_item)
            
            # Send welcome email
            welcome_msg = f"Welcome to TutorMatch, {name}! Your account has been created successfully."
            send_email(email, "Welcome to TutorMatch", welcome_msg)
            
            # Send admin notification
            publish_to_sns(f'New user registered: {name} ({email})', 'New User Registration')
            
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            flash('Registration failed. Please try again.', 'danger')
    
    try:
        return render_template('register.html')
    except:
        return '''
            <h1>Register</h1>
            <form method="post">
            Name: <input name="name" required><br>
            Email: <input name="email" type="email" required><br>
            Password: <input name="password" type="password" required><br>
            Confirm Password: <input name="confirm_password" type="password" required><br>
            Phone: <input name="phone"><br>
            <button type="submit">Register</button>
            </form>
            <a href="/login">Already have an account? Login</a>
        '''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('student_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Email and password are required', 'danger')
            return render_template('login.html')

        try:
            # Validate user credentials
            user = users_table.get_item(Key={'email': email}).get('Item')

            if user and check_password_hash(user['password'], password):
                if user.get('status') != 'active':
                    flash('Account is inactive. Contact administrator.', 'warning')
                    return render_template('login.html')
                    
                session['email'] = email
                session['role'] = user.get('role', 'student')
                session['name'] = user.get('name', '')
                
                flash(f'Welcome back, {user.get("name", "")}!', 'success')
                return redirect(url_for('student_dashboard'))
            else:
                flash('Invalid email or password.', 'danger')
                
        except Exception as e:
            logger.error(f"Login error: {e}")
            flash('Login failed. Please try again.', 'danger')

    try:
        return render_template('login.html')
    except:
        return '''
            <h1>Login</h1>
            <form method="post">
            Email: <input name="email" type="email" required><br>
            Password: <input name="password" type="password" required><br>
            <button type="submit">Login</button>
            </form>
            <a href="/register">Don't have an account? Register</a>
        '''

@app.route('/student-dashboard')
def student_dashboard():
    if not is_logged_in():
        flash('Please log in to access the dashboard', 'warning')
        return redirect(url_for('login'))
    
    try:
        return render_template("student_dashboard.html", user_name=session.get('name'))
    except:
        return '''
        <h1>Student Dashboard</h1>
        <p>Welcome, ''' + session.get('name', 'Student') + '''!</p>
        <a href="/tutor-search">Search Tutors</a><br>
        <a href="/my-bookings">My Bookings</a><br>
        <a href="/logout">Logout</a>
        '''

@app.route('/tutor-search')
def tutor_search():
    try:
        # Get all active tutors from DynamoDB
        response = tutors_table.scan(
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': 'active'}
        )
        tutors_list = response.get('Items', [])
        
        # Process tutors data for template
        processed_tutors = []
        for tutor in tutors_list:
            processed_tutor = dict(tutor)
            processed_tutor['rate'] = safe_decimal_to_float(tutor.get('rate', 0))
            processed_tutor['rating'] = safe_decimal_to_float(tutor.get('rating', 0))
            processed_tutors.append(processed_tutor)
        
        return render_template("tutor_search.html", tutors=processed_tutors)
    except Exception as e:
        logger.error(f"Error fetching tutors: {e}")
        # Fallback HTML
        html = "<h1>Find Tutors</h1><p>Error loading tutors. Please try again.</p>"
        return html

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    try:
        tutor = tutors_table.get_item(Key={'tutor_id': tutor_id}).get('Item')
        if not tutor:
            abort(404)
        
        # Process tutor data
        processed_tutor = dict(tutor)
        processed_tutor['rate'] = safe_decimal_to_float(tutor.get('rate', 0))
        processed_tutor['rating'] = safe_decimal_to_float(tutor.get('rating', 0))
        
        return render_template("tutor_profile.html", tutor=processed_tutor, tutor_id=tutor_id)
    except Exception as e:
        logger.error(f"Error fetching tutor profile: {e}")
        abort(404)

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    if not is_logged_in():
        flash('Please log in to book a session', 'warning')
        return redirect(url_for('login'))
    
    try:
        tutor = tutors_table.get_item(Key={'tutor_id': tutor_id}).get('Item')
        if not tutor:
            abort(404)
        
        if request.method == 'POST':
            booking_id = str(uuid.uuid4())
            date = request.form.get('date')
            time = request.form.get('time')
            subject = request.form.get('subject')
            session_type = request.form.get('session_type', 'Single Session')
            sessions_count = safe_to_int(request.form.get('sessions_count', 1))
            total_price = safe_decimal_to_float(tutor.get('rate', 25)) * sessions_count
            learning_goals = request.form.get('learning_goals', '')
            session_format = request.form.get('session_format', 'Online Video Call')

            booking_item = {
                "booking_id": booking_id,
                "tutor_id": tutor_id,
                "student_email": session.get('email'),
                "student_name": session.get('name'),
                "tutor_name": tutor.get('name'),
                "date": date,
                "time": time,
                "subject": subject,
                "session_type": session_type,
                "sessions_count": sessions_count,
                "total_price": safe_to_decimal(total_price),
                "learning_goals": learning_goals,
                "session_format": session_format,
                "status": "pending_payment",
                "created_at": datetime.now().isoformat()
            }
            
            bookings_table.put_item(Item=booking_item)
            
            # Send notifications
            publish_to_sns(
                f'New booking created: {session.get("name")} booked {tutor.get("name")} for {subject}',
                'New Booking Created'
            )
            
            return redirect(url_for("payment", booking_id=booking_id))

        # Process tutor data for GET request
        processed_tutor = dict(tutor)
        processed_tutor['rate'] = safe_decimal_to_float(tutor.get('rate', 0))
        processed_tutor['rating'] = safe_decimal_to_float(tutor.get('rating', 0))
        
        return render_template("booksession.html", tutor=processed_tutor, tutor_id=tutor_id)
        
    except Exception as e:
        logger.error(f"Error in book_session: {e}")
        flash('Error booking session. Please try again.', 'danger')
        return redirect(url_for('tutor_search'))

@app.route('/payment')
def payment():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    booking_id = request.args.get('booking_id')
    if not booking_id:
        abort(404)
    
    try:
        booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
        if not booking:
            abort(404)
        
        # Process booking data
        processed_booking = dict(booking)
        processed_booking['total_price'] = safe_decimal_to_float(booking.get('total_price', 0))
        
        return render_template("payment.html", booking=processed_booking, booking_id=booking_id)
    except Exception as e:
        logger.error(f"Error loading payment page: {e}")
        return f"<h1>Pay ${safe_decimal_to_float(booking.get('total_price', 0))}</h1><form method='post' action='/process-payment'><input name='booking_id' value='{booking_id}' hidden><button>Pay Now</button></form>"

@app.route('/process-payment', methods=['POST'])
def process_payment():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    booking_id = request.form.get('booking_id')
    payment_method = request.form.get('payment_method', 'credit_card')
    
    try:
        booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
        if not booking:
            abort(404)
        
        payment_id = str(uuid.uuid4())
        payment_item = {
            "payment_id": payment_id,
            "booking_id": booking_id,
            "student_email": session.get('email'),
            "amount": booking.get('total_price', safe_to_decimal(0)),
            "payment_method": payment_method,
            "status": "completed",
            "created_at": datetime.now().isoformat()
        }
        
        # Save payment
        payments_table.put_item(Item=payment_item)
        
        # Update booking status
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression='SET #status = :status, payment_id = :payment_id',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'confirmed',
                ':payment_id': payment_id
            }
        )
        
        # Send confirmation email
        tutor_name = booking.get('tutor_name', 'your tutor')
        subject = booking.get('subject', 'your session')
        session_date = booking.get('date', '')
        session_time = booking.get('time', '')
        
        email_body = f"""
        Dear {session.get('name')},
        
        Your tutoring session has been confirmed!
        
        Details:
        - Tutor: {tutor_name}
        - Subject: {subject}
        - Date: {session_date}
        - Time: {session_time}
        - Amount Paid: ${safe_decimal_to_float(booking.get('total_price', 0))}
        
        Thank you for using TutorMatch!
        """
        
        send_email(session.get('email'), "Session Confirmed - TutorMatch", email_body)
        
        # Send notifications
        publish_to_sns(
            f'Payment completed: {session.get("name")} paid ${safe_decimal_to_float(booking.get("total_price", 0))} for session with {tutor_name}',
            'Payment Completed'
        )
        
        return redirect(url_for('confirmation', booking_id=booking_id))
        
    except Exception as e:
        logger.error(f"Error processing payment: {e}")
        flash('Payment processing failed. Please try again.', 'danger')
        return redirect(url_for('payment', booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    booking_id = request.args.get('booking_id')
    if not booking_id:
        abort(404)
    
    try:
        booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
        if not booking:
            abort(404)
        
        # Process booking data
        processed_booking = dict(booking)
        processed_booking['total_price'] = safe_decimal_to_float(booking.get('total_price', 0))
        
        return render_template("confirmation.html", booking=processed_booking)
    except Exception as e:
        logger.error(f"Error loading confirmation: {e}")
        return f"<h1>Booking Confirmed</h1><p>Session with {booking.get('tutor_name', 'your tutor')} confirmed.</p><a href='/student-dashboard'>Back to Dashboard</a>"

@app.route('/my-bookings')
def my_bookings():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    try:
        # Get user's bookings
        response = bookings_table.scan(
            FilterExpression='student_email = :email',
            ExpressionAttributeValues={':email': session.get('email')}
        )
        
        bookings_list = response.get('Items', [])
        
        # Process bookings data
        processed_bookings = []
        for booking in bookings_list:
            processed_booking = dict(booking)
            processed_booking['total_price'] = safe_decimal_to_float(booking.get('total_price', 0))
            processed_bookings.append(processed_booking)
        
        # Sort by created_at (most recent first)
        processed_bookings.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return render_template("my_bookings.html", bookings=processed_bookings)
        
    except Exception as e:
        logger.error(f"Error fetching bookings: {e}")
        flash('Error loading bookings', 'danger')
        return redirect(url_for('student_dashboard'))

@app.route('/api/student-data')
def student_data():
    if not is_logged_in():
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        student_email = session.get('email')
        
        # Get bookings
        bookings_response = bookings_table.scan(
            FilterExpression='student_email = :email',
            ExpressionAttributeValues={':email': student_email}
        )
        
        # Get payments
        payments_response = payments_table.scan(
            FilterExpression='student_email = :email',
            ExpressionAttributeValues={':email': student_email}
        )
        
        student_bookings = []
        student_payments = []
        notifications = []
        
        # Process bookings
        for booking in bookings_response.get('Items', []):
            student_bookings.append({
                "id": booking.get("booking_id"),
                "tutor_name": booking.get("tutor_name"),
                "subject": booking.get("subject"),
                "date": booking.get("date"),
                "time": booking.get("time"),
                "status": booking.get("status"),
                "total_price": safe_decimal_to_float(booking.get("total_price", 0)),
                "session_format": booking.get("session_format"),
                "created_at": booking.get("created_at")
            })
            
            # Add notification for confirmed sessions
            if booking.get("status") == "confirmed":
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your session with {booking.get('tutor_name')} is confirmed.",
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
        
        # Process payments
        for payment in payments_response.get('Items', []):
            student_payments.append({
                "id": payment.get("payment_id"),
                "amount": safe_decimal_to_float(payment.get("amount", 0)),
                "status": payment.get("status"),
                "method": payment.get("payment_method"),
                "date": payment.get("created_at")
            })
        
        return jsonify({
            "bookings": student_bookings,
            "payments": student_payments,
            "notifications": notifications
        })
        
    except Exception as e:
        logger.error(f"Error fetching student data: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    try:
        # Check DynamoDB connection
        tutors_response = tutors_table.scan(Limit=1)
        tutors_count = tutors_response.get('Count', 0)
        
        return jsonify({
            "status": "healthy",
            "tutors_count": tutors_count,
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
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
