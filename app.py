from flask import Flask, render_template, request, redirect, url_for, jsonify, abort, session
from datetime import datetime, timedelta
import boto3
import json
import uuid
import os
from decimal import Decimal
from botocore.exceptions import ClientError

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

# AWS Configuration
AWS_REGION = 'us-east-1'
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
sns = boto3.client('sns', region_name='ap-south-1')  # SNS is in ap-south-1

# DynamoDB tables
users_table = dynamodb.Table('Users')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')
sessions_table = dynamodb.Table('Sessions')
tutors_table = dynamodb.Table('Tutors')

def convert_floats_to_decimal(obj):
    """Convert float values to Decimal for DynamoDB compatibility"""
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def initialize_tutors():
    """Initialize default tutors in DynamoDB if they don't exist"""
    default_tutors = {
        "tutor1": {
            "tutor_id": "tutor1",
            "name": "John Smith",
            "subjects": ["Mathematics", "Physics"],
            "rate": 30,
            "rating": 4.8,
            "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
            "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"]
        },
        "tutor2": {
            "tutor_id": "tutor2",
            "name": "Sarah Johnson",
            "subjects": ["English", "Literature"],
            "rate": 25,
            "rating": 4.6,
            "bio": "English literature specialist, helping students excel in writing and analysis.",
            "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"]
        }
    }
    
    for tutor_id, tutor_data in default_tutors.items():
        try:
            # Convert floats to Decimal for DynamoDB
            tutor_data_decimal = convert_floats_to_decimal(tutor_data)
            tutors_table.put_item(
                Item=tutor_data_decimal,
                ConditionExpression='attribute_not_exists(tutor_id)'
            )
            print(f"Added tutor: {tutor_id}")
        except ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                print(f"Error adding tutor {tutor_id}: {e}")
            else:
                print(f"Tutor {tutor_id} already exists")

def get_all_tutors():
    """Get all tutors from DynamoDB"""
    try:
        response = tutors_table.scan()
        tutors = {}
        for item in response['Items']:
            # Convert Decimal back to float for JSON serialization
            item_converted = json.loads(json.dumps(item, default=str))
            tutors[item['tutor_id']] = item_converted
        return tutors
    except ClientError as e:
        print(f"Error getting tutors: {e}")
        return {}

def get_tutor(tutor_id):
    """Get a specific tutor from DynamoDB"""
    try:
        response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        item = response.get('Item')
        if item:
            # Convert Decimal back to float for JSON serialization
            return json.loads(json.dumps(item, default=str))
        return None
    except ClientError as e:
        print(f"Error getting tutor {tutor_id}: {e}")
        return None

def get_user(email):
    """Get user from DynamoDB"""
    try:
        response = users_table.get_item(Key={'email': email})
        return response.get('Item')
    except ClientError as e:
        print(f"Error getting user {email}: {e}")
        return None

def create_user(email, password, name):
    """Create a new user in DynamoDB"""
    try:
        user_data = {
            'email': email,
            'password': password,
            'name': name,
            'created_at': datetime.now().isoformat()
        }
        users_table.put_item(Item=user_data)
        print(f"User created successfully: {email}")
        return True
    except ClientError as e:
        print(f"Error creating user: {e}")
        return False

def create_booking(booking_data):
    """Create a booking in DynamoDB"""
    try:
        # Convert floats to Decimal for DynamoDB
        booking_data_decimal = convert_floats_to_decimal(booking_data)
        bookings_table.put_item(Item=booking_data_decimal)
        return True
    except ClientError as e:
        print(f"Error creating booking: {e}")
        return False

def get_booking(booking_id):
    """Get booking from DynamoDB"""
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        item = response.get('Item')
        if item:
            # Convert Decimal back to regular numbers for JSON serialization
            return json.loads(json.dumps(item, default=str))
        return None
    except ClientError as e:
        print(f"Error getting booking {booking_id}: {e}")
        return None

def update_booking_status(booking_id, status, payment_id=None):
    """Update booking status in DynamoDB"""
    try:
        update_expression = "SET #status = :status"
        expression_attribute_names = {'#status': 'status'}
        expression_attribute_values = {':status': status}
        
        if payment_id:
            update_expression += ", payment_id = :payment_id"
            expression_attribute_values[':payment_id'] = payment_id
        
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values
        )
        return True
    except ClientError as e:
        print(f"Error updating booking: {e}")
        return False

def create_payment(payment_data):
    """Create a payment record in DynamoDB"""
    try:
        # Convert floats to Decimal for DynamoDB
        payment_data_decimal = convert_floats_to_decimal(payment_data)
        payments_table.put_item(Item=payment_data_decimal)
        return True
    except ClientError as e:
        print(f"Error creating payment: {e}")
        return False

def get_user_bookings(user_email):
    """Get all bookings for a user"""
    try:
        response = bookings_table.scan(
            FilterExpression='attribute_exists(user_email) AND user_email = :email',
            ExpressionAttributeValues={':email': user_email}
        )
        items = response.get('Items', [])
        # Convert Decimal back to regular numbers for JSON serialization
        return [json.loads(json.dumps(item, default=str)) for item in items]
    except ClientError as e:
        print(f"Error getting user bookings: {e}")
        return []

def get_user_payments(user_email):
    """Get all payments for a user"""
    try:
        response = payments_table.scan(
            FilterExpression='attribute_exists(user_email) AND user_email = :email',
            ExpressionAttributeValues={':email': user_email}
        )
        items = response.get('Items', [])
        # Convert Decimal back to regular numbers for JSON serialization
        return [json.loads(json.dumps(item, default=str)) for item in items]
    except ClientError as e:
        print(f"Error getting user payments: {e}")
        return []

def send_notification(subject, message, user_email=None):
    """Send notification via SNS"""
    try:
        full_message = f"TutorMatch Notification\n\nUser: {user_email if user_email else 'System'}\n\n{message}\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        response = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=full_message
        )
        print(f"Notification sent successfully: {subject} - MessageId: {response.get('MessageId')}")
        return True
    except ClientError as e:
        print(f"Error sending notification: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error sending notification: {e}")
        return False

# Initialize tutors on startup
initialize_tutors()

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
        user = get_user(email)
        if user and user['password'] == password:
            session['user_email'] = email  # Store user in session
            session['user_name'] = user['name']
            print(f"User logged in: {email}")
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
    try:
        return render_template('login.html')
    except:
        return '''
            <h1>Login</h1>
            <form method="post">
            Email: <input name="email" type="email" required><br><br>
            Password: <input name="password" type="password" required><br><br>
            <button type="submit">Login</button>
            </form>
        '''

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        
        if get_user(email):
            return "User already exists", 400
        
        if create_user(email, password, name):
            send_notification("New User Registration", f"New user registered: {name} ({email})")
            return redirect(url_for('login'))
        else:
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
    tutors_data = get_all_tutors()
    try:
        tutors_with_id = [{"id": k, **v} for k, v in tutors_data.items()]
        return render_template("tutor_search.html", tutors_with_id=tutors_with_id)
    except:
        html = ""
        for tid, t in tutors_data.items():
            html += f"<h3>{t['name']}</h3><a href='/tutor-profile/{tid}'>View Profile</a><hr>"
        return f"<h1>Find Tutors</h1>{html}"

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    tutor = get_tutor(tutor_id)
    if not tutor:
        abort(404)
    try:
        return render_template("tutor_profile.html", tutor=tutor, tutor_id=tutor_id)
    except:
        return f"<h1>{tutor['name']}</h1><a href='/book-session/{tutor_id}'>Book Session</a>"

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    # Check if user is logged in
    if 'user_email' not in session:
        return redirect(url_for('login'))
    
    tutor = get_tutor(tutor_id)
    if not tutor:
        abort(404)
    
    if request.method == 'POST':
        booking_id = str(uuid.uuid4())
        date = request.form['date']
        time = request.form['time']
        subject = request.form['subject']
        session_type = request.form.get('session_type', 'Single Session')
        sessions_count = int(request.form.get('sessions_count', 1))
        total_price = float(tutor.get('rate', 25)) * sessions_count
        learning_goals = request.form.get('learning_goals', '')
        session_format = request.form.get('session_format', 'Online Video Call')
        user_email = session['user_email']

        booking_data = {
            "booking_id": booking_id,
            "tutor_id": tutor_id,
            "tutor_data": tutor,
            "user_email": user_email,
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
        
        print(f"Creating booking: {booking_data}")
        
        if create_booking(booking_data):
            # Send booking notification
            send_notification(
                "New Booking Created", 
                f"New booking created:\n- Tutor: {tutor['name']}\n- Date: {date}\n- Time: {time}\n- Subject: {subject}\n- User: {user_email}",
                user_email
            )
            print(f"Booking created successfully: {booking_id}")
            return redirect(url_for("payment", booking_id=booking_id))
        else:
            print("Failed to create booking")
            return "Booking failed", 500

    try:
        return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)
    except:
        return f'''
            <h1>Book Session with {tutor['name']}</h1>
            <form method="post">
            Date: <input name="date" type="date" required><br><br>
            Time: <input name="time" type="time" required><br><br>
            Subject: <input name="subject" required><br><br>
            Sessions Count: <input name="sessions_count" type="number" value="1" min="1"><br><br>
            Session Type: 
            <select name="session_type">
                <option value="Single Session">Single Session</option>
                <option value="Package">Package</option>
            </select><br><br>
            Learning Goals: <textarea name="learning_goals"></textarea><br><br>
            Session Format:
            <select name="session_format">
                <option value="Online Video Call">Online Video Call</option>
                <option value="In Person">In Person</option>
            </select><br><br>
            <button type="submit">Book Session</button>
            </form>
        '''

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    booking = get_booking(booking_id)
    if not booking:
        abort(404)
    try:
        return render_template("payment.html", booking=booking, booking_id=booking_id)
    except:
        return f'''
            <h1>Pay ${booking['total_price']}</h1>
            <form method='post' action='/process-payment'>
                <input name='booking_id' value='{booking_id}' type='hidden'>
                <input name='payment_method' placeholder='Payment Method'><br>
                <input name='email' placeholder='Email' type='email'><br>
                <input name='phone' placeholder='Phone'><br>
                <button>Pay</button>
            </form>
        '''

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form.get('payment_method', 'Credit Card')
    
    # Get user info from session
    if 'user_email' not in session:
        return redirect(url_for('login'))
    
    user_email = session['user_email']
    phone = request.form.get('phone', '')
    
    booking = get_booking(booking_id)
    if not booking:
        abort(404)
    
    payment_id = str(uuid.uuid4())
    payment_data = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "user_email": user_email,
        "amount": float(booking["total_price"]),
        "payment_method": payment_method,
        "phone": phone,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }
    
    print(f"Processing payment: {payment_data}")
    
    if create_payment(payment_data) and update_booking_status(booking_id, "confirmed", payment_id):
        # Send payment confirmation notification
        send_notification(
            "Payment Successful - TutorMatch", 
            f"Payment Confirmation:\n- Amount: ${booking['total_price']}\n- Booking ID: {booking_id}\n- Tutor: {booking['tutor_data']['name']}\n- Date: {booking['date']}\n- Time: {booking['time']}\n- Payment Method: {payment_method}",
            user_email
        )
        
        # Send session reminder notification
        session_datetime = datetime.strptime(f"{booking['date']} {booking['time']}", "%Y-%m-%d %H:%M")
        send_notification(
            "Upcoming Session Reminder - TutorMatch",
            f"Session Reminder:\n- Tutor: {booking['tutor_data']['name']}\n- Subject: {booking['subject']}\n- Date: {booking['date']}\n- Time: {booking['time']}\n- Format: {booking['session_format']}\n- Learning Goals: {booking.get('learning_goals', 'N/A')}",
            user_email
        )
        
        print(f"Payment processed successfully: {payment_id}")
        return redirect(url_for('confirmation', booking_id=booking_id))
    else:
        print("Payment processing failed")
        return "Payment processing failed", 500

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    booking = get_booking(booking_id)
    if not booking:
        abort(404)
    try:
        return render_template("confirmation.html", booking=booking)
    except:
        return f"<h1>Booking Confirmed</h1><p>Session with {booking['tutor_data']['name']} confirmed.</p>"

@app.route('/api/student-data')
def student_data():
    if 'user_email' not in session:
        return jsonify({"error": "User not logged in"}), 401
        
    user_email = session['user_email']
    
    student_bookings = []
    student_payments = []
    notifications = []
    
    # Get user bookings
    bookings = get_user_bookings(user_email)
    print(f"Found {len(bookings)} bookings for user {user_email}")
    
    for b in bookings:
        student_bookings.append({
            "id": b["booking_id"],
            "tutor_name": b["tutor_data"]["name"],
            "subject": b["subject"],
            "date": b["date"],
            "time": b["time"],
            "status": b["status"],
            "total_price": b["total_price"],
            "session_format": b["session_format"],
            "created_at": b["created_at"]
        })
        
        if b["status"] == "confirmed":
            notifications.append({
                "type": "success",
                "title": "Session Confirmed",
                "message": f"Your session with {b['tutor_data']['name']} on {b['date']} at {b['time']} is confirmed.",
                "date": datetime.now().strftime("%Y-%m-%d")
            })
    
    # Get user payments
    payments = get_user_payments(user_email)
    print(f"Found {len(payments)} payments for user {user_email}")
    
    for p in payments:
        student_payments.append({
            "id": p["payment_id"],
            "amount": p["amount"],
            "status": p["status"],
            "method": p["payment_method"],
            "date": p["created_at"]
        })
    
    return jsonify({
        "bookings": student_bookings,
        "payments": student_payments,
        "notifications": notifications
    })

@app.route('/logout')
def logout():
    session.clear()  # Clear session data
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    try:
        tutors_count = len(get_all_tutors())
        return jsonify({
            "status": "healthy",
            "tutors_count": tutors_count,
            "aws_region": AWS_REGION,
            "dynamodb": "connected"
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

@app.route('/admin/stats')
def admin_stats():
    """Admin endpoint to view system statistics"""
    try:
        tutors = get_all_tutors()
        
        # Get counts from DynamoDB
        bookings_response = bookings_table.scan(Select='COUNT')
        payments_response = payments_table.scan(Select='COUNT')
        users_response = users_table.scan(Select='COUNT')
        
        stats = {
            "tutors_count": len(tutors),
            "bookings_count": bookings_response['Count'],
            "payments_count": payments_response['Count'],
            "users_count": users_response['Count'],
            "aws_region": AWS_REGION
        }
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Add debugging route to check data
@app.route('/debug/tables')
def debug_tables():
    """Debug endpoint to check table contents"""
    try:
        # Check tutors
        tutors_response = tutors_table.scan()
        tutors_count = len(tutors_response.get('Items', []))
        
        # Check bookings
        bookings_response = bookings_table.scan()
        bookings_count = len(bookings_response.get('Items', []))
        
        # Check payments
        payments_response = payments_table.scan()
        payments_count = len(payments_response.get('Items', []))
        
        # Check users
        users_response = users_table.scan()
        users_count = len(users_response.get('Items', []))
        
        debug_info = {
            "tutors": {
                "count": tutors_count,
                "items": [item['tutor_id'] for item in tutors_response.get('Items', [])]
            },
            "bookings": {
                "count": bookings_count,
                "items": [item['booking_id'] for item in bookings_response.get('Items', [])]
            },
            "payments": {
                "count": payments_count,
                "items": [item['payment_id'] for item in payments_response.get('Items', [])]
            },
            "users": {
                "count": users_count,
                "items": [item['email'] for item in users_response.get('Items', [])]
            }
        }
        
        return jsonify(debug_info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Starting TutorMatch application...")
    print("Initializing tutors...")
    initialize_tutors()
    print("Application ready!")
    app.run(host='0.0.0.0', port=8000, debug=True)
