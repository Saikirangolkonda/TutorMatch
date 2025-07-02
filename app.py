from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime, timedelta
import os, json, uuid
import boto3
from botocore.exceptions import ClientError
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS DynamoDB setup
dynamodb = boto3.resource('dynamodb', region_name='your-region')
users_table = dynamodb.Table('Users')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')
sessions_table = dynamodb.Table('Sessions')
tutors_table = dynamodb.Table('Tutors')

# Email configuration for notifications
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_ADDRESS = "your-email@gmail.com"
EMAIL_PASSWORD = "your-app-password"

# Load tutor data and store in database
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
def initialize_tutors():
    if os.path.exists(TUTORS_FILE):
        with open(TUTORS_FILE) as f:
            tutors_data = json.load(f)
    else:
        tutors_data = {
            "tutor1": {
                "name": "John Smith",
                "subjects": ["Mathematics", "Physics"],
                "rate": 30,
                "rating": 4.8,
                "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
                "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"],
                "email": "john.smith@example.com"
            },
            "tutor2": {
                "name": "Sarah Johnson",
                "subjects": ["English", "Literature"],
                "rate": 25,
                "rating": 4.6,
                "bio": "English literature specialist, helping students excel in writing and analysis.",
                "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"],
                "email": "sarah.johnson@example.com"
            }
        }
        os.makedirs("templates", exist_ok=True)
        with open(TUTORS_FILE, "w") as f:
            json.dump(tutors_data, f, indent=2)
    
    # Store tutors in database
    for tutor_id, tutor_data in tutors_data.items():
        try:
            tutors_table.put_item(
                Item={
                    'tutor_id': tutor_id,
                    **tutor_data,
                    'created_at': datetime.now().isoformat()
                }
            )
        except Exception as e:
            print(f"Error storing tutor {tutor_id}: {e}")

# Initialize tutors on startup
initialize_tutors()

def send_email_notification(to_email, subject, message):
    """Send email notification"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(message, 'plain'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def send_sms_notification(phone_number, message):
    """Send SMS notification using AWS SNS"""
    try:
        sns = boto3.client('sns', region_name='your-region')
        response = sns.publish(
            PhoneNumber=phone_number,
            Message=message
        )
        return True
    except Exception as e:
        print(f"Failed to send SMS: {e}")
        return False

@app.route('/')
def homepage():
    try:
        return render_template("homepage.html")
    except:
        return """
        <h1>Welcome to TutorMatch</h1>
        <a href='/login'>Login</a> | <a href='/register'>Register</a>
        """

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            response = users_table.get_item(Key={'email': email})
            if 'Item' in response and response['Item']['password'] == password:
                return redirect(url_for('student_dashboard'))
            return "Invalid credentials", 401
        except Exception as e:
            print(f"Login error: {e}")
            return "Login failed", 500
            
    try:
        return render_template('login.html')
    except:
        return '''
            <h1>Login</h1>
            <form method="post">
            Email: <input name="email"><br>
            Password: <input name="password"><br>
            <button type="submit">Login</button>
            </form>
        '''

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        
        try:
            # Check if user already exists
            response = users_table.get_item(Key={'email': email})
            if 'Item' in response:
                return "User already exists", 400
            
            # Create new user
            users_table.put_item(
                Item={
                    'email': email,
                    'password': password,
                    'name': name,
                    'created_at': datetime.now().isoformat()
                }
            )
            
            # Send welcome email
            send_email_notification(
                email, 
                "Welcome to TutorMatch!", 
                f"Hi {name}, welcome to TutorMatch! You can now search and book tutoring sessions."
            )
            
            return redirect(url_for('login'))
        except Exception as e:
            print(f"Registration error: {e}")
            return "Registration failed", 500
            
    try:
        return render_template('register.html')
    except:
        return '''
            <h1>Register</h1>
            <form method="post">
            Name: <input name="name"><br>
            Email: <input name="email"><br>
            Password: <input name="password"><br>
            <button type="submit">Register</button>
            </form>
        '''

@app.route('/student-dashboard')
def student_dashboard():
    try:
        return render_template("student_dashboard.html")
    except:
        return '''
        <h1>Student Dashboard</h1>
        <a href="/tutor-search">Search Tutors</a>
        '''

@app.route('/tutor-search')
def tutor_search():
    try:
        # Get tutors from database
        response = tutors_table.scan()
        tutors_with_id = []
        for item in response['Items']:
            tutors_with_id.append({
                "id": item['tutor_id'],
                **{k: v for k, v in item.items() if k != 'tutor_id'}
            })
        return render_template("tutor_search.html", tutors_with_id=tutors_with_id)
    except Exception as e:
        print(f"Tutor search error: {e}")
        return "<h1>Error loading tutors</h1>"

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    try:
        response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        if 'Item' not in response:
            abort(404)
        tutor = response['Item']
        return render_template("tutor_profile.html", tutor=tutor, tutor_id=tutor_id)
    except Exception as e:
        print(f"Tutor profile error: {e}")
        abort(404)

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    try:
        response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        if 'Item' not in response:
            abort(404)
        tutor = response['Item']
    except Exception as e:
        print(f"Book session error: {e}")
        abort(404)
    
    if request.method == 'POST':
        booking_id = str(uuid.uuid4())
        date = request.form['date']
        time = request.form['time']
        subject = request.form['subject']
        session_type = request.form.get('session_type', 'Single Session')
        sessions_count = int(request.form.get('sessions_count', 1))
        total_price = int(tutor.get('rate', 25)) * sessions_count
        learning_goals = request.form.get('learning_goals', '')
        session_format = request.form.get('session_format', 'Online Video Call')
        student_email = request.form.get('student_email', '')
        student_phone = request.form.get('student_phone', '')

        try:
            # Store booking in database
            booking_data = {
                "booking_id": booking_id,
                "tutor_id": tutor_id,
                "tutor_name": tutor['name'],
                "tutor_email": tutor.get('email', ''),
                "student_email": student_email,
                "student_phone": student_phone,
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
            print(f"Booking creation error: {e}")
            return "Booking failed", 500

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        if 'Item' not in response:
            abort(404)
        booking = response['Item']
        return render_template("payment.html", booking=booking, booking_id=booking_id)
    except Exception as e:
        print(f"Payment page error: {e}")
        abort(404)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form['payment_method']
    email = request.form['email']
    phone = request.form['phone']
    
    try:
        # Get booking
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        if 'Item' not in response:
            abort(404)
        booking = response['Item']
        
        # Create payment record
        payment_id = str(uuid.uuid4())
        payment_data = {
            "payment_id": payment_id,
            "booking_id": booking_id,
            "amount": booking["total_price"],
            "payment_method": payment_method,
            "status": "completed",
            "student_email": email,
            "student_phone": phone,
            "created_at": datetime.now().isoformat()
        }
        
        payments_table.put_item(Item=payment_data)
        
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
        
        # Create session record
        session_id = str(uuid.uuid4())
        sessions_table.put_item(
            Item={
                'session_id': session_id,
                'booking_id': booking_id,
                'tutor_id': booking['tutor_id'],
                'student_email': email,
                'date': booking['date'],
                'time': booking['time'],
                'subject': booking['subject'],
                'status': 'scheduled',
                'created_at': datetime.now().isoformat()
            }
        )
        
        # Send notifications
        # Email to student
        student_message = f"""
        Hi there!
        
        Your tutoring session has been confirmed:
        - Tutor: {booking['tutor_name']}
        - Subject: {booking['subject']}
        - Date: {booking['date']}
        - Time: {booking['time']}
        - Format: {booking['session_format']}
        
        Session ID: {session_id}
        
        Thank you for choosing TutorMatch!
        """
        
        send_email_notification(email, "Session Confirmed - TutorMatch", student_message)
        
        # Email to tutor
        if booking.get('tutor_email'):
            tutor_message = f"""
            Hi {booking['tutor_name']},
            
            You have a new tutoring session:
            - Student: {email}
            - Subject: {booking['subject']}
            - Date: {booking['date']}
            - Time: {booking['time']}
            - Format: {booking['session_format']}
            
            Session ID: {session_id}
            
            Please prepare for the session and contact the student if needed.
            """
            
            send_email_notification(booking['tutor_email'], "New Session Booked - TutorMatch", tutor_message)
        
        # SMS notification if phone provided
        if phone:
            sms_message = f"TutorMatch: Your session with {booking['tutor_name']} on {booking['date']} at {booking['time']} is confirmed. Session ID: {session_id}"
            send_sms_notification(phone, sms_message)
        
        return redirect(url_for('confirmation', booking_id=booking_id))
        
    except Exception as e:
        print(f"Payment processing error: {e}")
        return "Payment processing failed", 500

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        if 'Item' not in response:
            abort(404)
        booking = response['Item']
        return render_template("confirmation.html", booking=booking)
    except Exception as e:
        print(f"Confirmation error: {e}")
        abort(404)

@app.route('/api/student-data')
def student_data():
    try:
        # Get all bookings
        bookings_response = bookings_table.scan()
        student_bookings = []
        student_payments = []
        notifications = []
        
        for booking in bookings_response['Items']:
            student_bookings.append({
                "id": booking["booking_id"],
                "tutor_name": booking["tutor_name"],
                "subject": booking["subject"],
                "date": booking["date"],
                "time": booking["time"],
                "status": booking["status"],
                "total_price": booking["total_price"],
                "session_format": booking["session_format"],
                "created_at": booking["created_at"]
            })
            
            # Get payment if exists
            if booking.get("payment_id"):
                try:
                    payment_response = payments_table.get_item(Key={'payment_id': booking["payment_id"]})
                    if 'Item' in payment_response:
                        payment = payment_response['Item']
                        student_payments.append({
                            "id": payment["payment_id"],
                            "amount": payment["amount"],
                            "status": payment["status"],
                            "method": payment["payment_method"],
                            "date": payment["created_at"]
                        })
                except Exception as e:
                    print(f"Error fetching payment: {e}")
            
            # Create notifications
            if booking["status"] == "confirmed":
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your session with {booking['tutor_name']} is confirmed.",
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
        
        return jsonify({
            "bookings": student_bookings,
            "payments": student_payments,
            "notifications": notifications
        })
        
    except Exception as e:
        print(f"Student data API error: {e}")
        return jsonify({"error": "Failed to fetch data"}), 500

@app.route('/logout')
def logout():
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    try:
        tutors_response = tutors_table.scan()
        return jsonify({
            "status": "healthy", 
            "tutors_count": len(tutors_response['Items']),
            "database": "connected"
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "database": "disconnected"
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
