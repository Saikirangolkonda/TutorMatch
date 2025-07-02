from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime, timedelta
import os, json, uuid, boto3
from botocore.exceptions import ClientError

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key')

# AWS Configuration
AWS_REGION = os.environ.get('AWS_REGION', 'ap-south-1')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications')

# Initialize AWS clients
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    sns_client = boto3.client('sns', region_name=AWS_REGION)
    
    # DynamoDB Tables
    users_table = dynamodb.Table('Users')
    tutors_table = dynamodb.Table('Tutors')
    bookings_table = dynamodb.Table('Bookings')
    payments_table = dynamodb.Table('Payments')
    sessions_table = dynamodb.Table('Sessions')
except:
    # Fallback for local development
    dynamodb = None
    sns_client = None

# Default tutor data and in-memory storage for fallback
tutors_data = {
    "tutor1": {
        "name": "John Smith",
        "subjects": ["Mathematics", "Physics"],
        "rate": 30,
        "rating": 4.8,
        "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
        "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"]
    },
    "tutor2": {
        "name": "Sarah Johnson",
        "subjects": ["English", "Literature"],
        "rate": 25,
        "rating": 4.6,
        "bio": "English literature specialist, helping students excel in writing and analysis.",
        "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"]
    }
}

users = {}
bookings = {}
payments = {}

# Initialize default tutors in DynamoDB
def initialize_tutors():
    if not dynamodb:
        return
    try:
        for tid, tutor in tutors_data.items():
            tutor_data = tutor.copy()
            tutor_data['tutor_id'] = tid
            tutor_data['created_at'] = datetime.now().isoformat()
            tutors_table.put_item(Item=tutor_data, ConditionExpression='attribute_not_exists(tutor_id)')
    except:
        pass

def send_notification(email, subject, message):
    if not sns_client:
        return False
    try:
        sns_message = {
            "default": message,
            "email": f"Subject: {subject}\n\n{message}"
        }
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(sns_message),
            Subject=subject,
            MessageStructure='json'
        )
        return True
    except:
        return False

def get_all_tutors():
    if not dynamodb:
        return tutors_data
    try:
        response = tutors_table.scan()
        tutors = {}
        for item in response['Items']:
            tutors[item['tutor_id']] = item
        return tutors if tutors else tutors_data
    except:
        return tutors_data

def get_tutor(tutor_id):
    if not dynamodb:
        return tutors_data.get(tutor_id)
    try:
        response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        return response.get('Item', tutors_data.get(tutor_id))
    except:
        return tutors_data.get(tutor_id)

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
        
        if dynamodb:
            try:
                response = users_table.get_item(Key={'email': email})
                user = response.get('Item')
                if user and user['password'] == password:
                    return redirect(url_for('student_dashboard'))
            except:
                pass
        else:
            if email in users and users[email]['password'] == password:
                return redirect(url_for('student_dashboard'))
        
        return "Invalid credentials", 401
    
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
        
        if dynamodb:
            try:
                response = users_table.get_item(Key={'email': email})
                if response.get('Item'):
                    return "User already exists", 400
                
                users_table.put_item(Item={
                    'email': email,
                    'password': password,
                    'name': name,
                    'created_at': datetime.now().isoformat()
                })
                
                welcome_message = f"Welcome to TutorMatch, {name}! Your account has been created successfully."
                send_notification(email, "Welcome to TutorMatch!", welcome_message)
                
                return redirect(url_for('login'))
            except:
                pass
        else:
            if email in users:
                return "User already exists", 400
            users[email] = {"email": email, "password": password, "name": name}
        
        return redirect(url_for('login'))
    
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
    tutors_data_current = get_all_tutors()
    try:
        return render_template("tutor_search.html", tutors_with_id=[{"id": k, **v} for k, v in tutors_data_current.items()])
    except:
        html = ""
        for tid, t in tutors_data_current.items():
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
        total_price = tutor.get('rate', 25) * sessions_count
        learning_goals = request.form.get('learning_goals', '')
        session_format = request.form.get('session_format', 'Online Video Call')

        booking_data = {
            "booking_id": booking_id, "tutor_id": tutor_id, "tutor_data": tutor,
            "date": date, "time": time, "subject": subject,
            "session_type": session_type, "sessions_count": sessions_count,
            "total_price": total_price, "learning_goals": learning_goals,
            "session_format": session_format, "status": "pending_payment",
            "created_at": datetime.now().isoformat()
        }

        if dynamodb:
            try:
                bookings_table.put_item(Item=booking_data)
            except:
                bookings[booking_id] = booking_data
        else:
            bookings[booking_id] = booking_data
        
        return redirect(url_for("payment", booking_id=booking_id))

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    
    if dynamodb:
        try:
            response = bookings_table.get_item(Key={'booking_id': booking_id})
            booking = response.get('Item')
        except:
            booking = bookings.get(booking_id)
    else:
        booking = bookings.get(booking_id)
    
    if not booking:
        abort(404)
    
    try:
        return render_template("payment.html", booking=booking, booking_id=booking_id)
    except:
        return f"<h1>Pay ${booking['total_price']}</h1><form method='post' action='/process-payment'><input name='booking_id' value='{booking_id}'><button>Pay</button></form>"

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form['payment_method']
    email = request.form['email']
    phone = request.form['phone']
    
    if dynamodb:
        try:
            response = bookings_table.get_item(Key={'booking_id': booking_id})
            booking = response.get('Item')
        except:
            booking = bookings.get(booking_id)
    else:
        booking = bookings.get(booking_id)
    
    if not booking:
        abort(404)
    
    payment_id = str(uuid.uuid4())
    payment_data = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "payment_method": payment_method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }
    
    if dynamodb:
        try:
            payments_table.put_item(Item=payment_data)
            bookings_table.update_item(
                Key={'booking_id': booking_id},
                UpdateExpression='SET #status = :status, payment_id = :payment_id',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'confirmed', ':payment_id': payment_id}
            )
            sessions_table.put_item(Item={
                'session_id': str(uuid.uuid4()),
                'booking_id': booking_id,
                'tutor_id': booking['tutor_id'],
                'student_email': email,
                'date': booking['date'],
                'time': booking['time'],
                'subject': booking['subject'],
                'status': 'scheduled',
                'created_at': datetime.now().isoformat()
            })
        except:
            payments[payment_id] = payment_data
            bookings[booking_id]["status"] = "confirmed"
            bookings[booking_id]["payment_id"] = payment_id
    else:
        payments[payment_id] = payment_data
        bookings[booking_id]["status"] = "confirmed"
        bookings[booking_id]["payment_id"] = payment_id
    
    # Send notifications
    payment_message = f"""Payment Confirmed!
    
Amount: ${booking['total_price']}
Tutor: {booking['tutor_data']['name']}
Session: {booking['date']} at {booking['time']}
Subject: {booking['subject']}

Thank you for choosing TutorMatch!"""
    
    send_notification(email, "Payment Confirmation - TutorMatch", payment_message)
    
    session_reminder = f"""Session Reminder!
    
Your session with {booking['tutor_data']['name']} is scheduled for:
Date: {booking['date']} at {booking['time']}
Subject: {booking['subject']}

Please be ready 5 minutes before the session."""
    
    send_notification(email, "Session Reminder - TutorMatch", session_reminder)
    
    return redirect(url_for('confirmation', booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    
    if dynamodb:
        try:
            response = bookings_table.get_item(Key={'booking_id': booking_id})
            booking = response.get('Item')
        except:
            booking = bookings.get(booking_id)
    else:
        booking = bookings.get(booking_id)
    
    if not booking:
        abort(404)
    
    try:
        return render_template("confirmation.html", booking=booking)
    except:
        return f"<h1>Booking Confirmed</h1><p>Session with {booking['tutor_data']['name']} confirmed.</p>"

@app.route('/api/student-data')
def student_data():
    student_bookings = []
    student_payments = []
    notifications = []
    
    if dynamodb:
        try:
            bookings_response = bookings_table.scan()
            for b in bookings_response['Items']:
                student_bookings.append({
                    "id": b["booking_id"], "tutor_name": b["tutor_data"]["name"], "subject": b["subject"],
                    "date": b["date"], "time": b["time"], "status": b["status"],
                    "total_price": b["total_price"], "session_format": b["session_format"],
                    "created_at": b["created_at"]
                })
                if b["status"] == "confirmed":
                    notifications.append({
                        "type": "success", "title": "Session Confirmed",
                        "message": f"Your session with {b['tutor_data']['name']} is confirmed.",
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
            
            payments_response = payments_table.scan()
            for p in payments_response['Items']:
                student_payments.append({
                    "id": p["payment_id"], "amount": p["amount"],
                    "status": p["status"], "method": p["payment_method"],
                    "date": p["created_at"]
                })
        except:
            for b in bookings.values():
                student_bookings.append({
                    "id": b["id"], "tutor_name": b["tutor_data"]["name"], "subject": b["subject"],
                    "date": b["date"], "time": b["time"], "status": b["status"],
                    "total_price": b["total_price"], "session_format": b["session_format"],
                    "created_at": b["created_at"]
                })
                if b["status"] == "confirmed":
                    notifications.append({
                        "type": "success", "title": "Session Confirmed",
                        "message": f"Your session with {b['tutor_data']['name']} is confirmed.",
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
            
            for p in payments.values():
                student_payments.append({
                    "id": p["id"], "amount": p["amount"],
                    "status": p["status"], "method": p["payment_method"],
                    "date": p["created_at"]
                })
    else:
        for b in bookings.values():
            student_bookings.append({
                "id": b["id"], "tutor_name": b["tutor_data"]["name"], "subject": b["subject"],
                "date": b["date"], "time": b["time"], "status": b["status"],
                "total_price": b["total_price"], "session_format": b["session_format"],
                "created_at": b["created_at"]
            })
            if b["status"] == "confirmed":
                notifications.append({
                    "type": "success", "title": "Session Confirmed",
                    "message": f"Your session with {b['tutor_data']['name']} is confirmed.",
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
        
        for p in payments.values():
            student_payments.append({
                "id": p["id"], "amount": p["amount"],
                "status": p["status"], "method": p["payment_method"],
                "date": p["created_at"]
            })
    
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
    tutors_count = len(get_all_tutors())
    return jsonify({"status": "healthy", "tutors_count": tutors_count})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
