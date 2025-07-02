# AWS-Compatible Flask App with DynamoDB and SNS Integration

from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import os, uuid, boto3

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS clients
region = 'ap-south-1'
dynamodb = boto3.resource('dynamodb', region_name=region)
sns = boto3.client('sns', region_name=region)
sns_topic_arn = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# DynamoDB tables
tables = {
    'users': dynamodb.Table('Users'),
    'tutors': dynamodb.Table('Tutors'),
    'bookings': dynamodb.Table('Bookings'),
    'payments': dynamodb.Table('Payments'),
    'sessions': dynamodb.Table('Sessions')
}

@app.route('/')
def homepage():
    return """
    <h1>Welcome to TutorMatch</h1>
    <a href='/login'>Login</a> | <a href='/register'>Register</a>
    """

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = tables['users'].get_item(Key={'email': email}).get('Item')
        if user and user['password'] == password:
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
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
        existing = tables['users'].get_item(Key={'email': email}).get('Item')
        if existing:
            return "User already exists", 400
        tables['users'].put_item(Item={'email': email, 'password': password, 'name': name})
        return redirect(url_for('login'))
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
    return '''
    <h1>Student Dashboard</h1>
    <a href="/tutor-search">Search Tutors</a>
    '''

@app.route('/tutor-search')
def tutor_search():
    tutors = tables['tutors'].scan().get('Items', [])
    html = ''.join([f"<h3>{t['name']}</h3><a href='/tutor-profile/{t['tutor_id']}'>View Profile</a><hr>" for t in tutors])
    return f"<h1>Find Tutors</h1>{html}"

@app.route('/tutor-profile/<tutor_id>')
def tutor_profile(tutor_id):
    tutor = tables['tutors'].get_item(Key={'tutor_id': tutor_id}).get('Item')
    if not tutor:
        abort(404)
    return f"<h1>{tutor['name']}</h1><a href='/book-session/{tutor_id}'>Book Session</a>"

@app.route('/book-session/<tutor_id>', methods=['GET', 'POST'])
def book_session(tutor_id):
    tutor = tables['tutors'].get_item(Key={'tutor_id': tutor_id}).get('Item')
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

        tables['bookings'].put_item(Item={
            "booking_id": booking_id, "tutor_id": tutor_id,
            "date": date, "time": time, "subject": subject,
            "session_type": session_type, "sessions_count": sessions_count,
            "total_price": total_price, "learning_goals": learning_goals,
            "session_format": session_format, "status": "pending_payment",
            "created_at": datetime.now().isoformat()
        })
        return redirect(url_for("payment", booking_id=booking_id))

    return f"<h1>Book Session with {tutor['name']}</h1>"

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')
    booking = tables['bookings'].get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return f"""
        <h1>Pay ${booking['total_price']}</h1>
        <form method='post' action='/process-payment'>
        <input name='booking_id' value='{booking_id}' hidden>
        Email: <input name='email'><br>
        Phone: <input name='phone'><br>
        Payment Method: <input name='payment_method'><br>
        <button>Pay</button>
        </form>
    """

@app.route('/process-payment', methods=['POST'])
def process_payment():
    booking_id = request.form['booking_id']
    payment_method = request.form['payment_method']
    email = request.form['email']
    phone = request.form['phone']
    booking = tables['bookings'].get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)
    payment_id = str(uuid.uuid4())
    tables['payments'].put_item(Item={
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking['total_price'],
        "payment_method": payment_method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    })
    tables['bookings'].update_item(
        Key={'booking_id': booking_id},
        UpdateExpression="SET #s = :s, payment_id = :pid",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "confirmed", ":pid": payment_id}
    )
    sns.publish(
        TopicArn=sns_topic_arn,
        Message=f"Your session with tutor {booking['tutor_id']} is confirmed.",
        Subject="TutorMatch: Session Confirmed"
    )
    return redirect(url_for('confirmation', booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    booking = tables['bookings'].get_item(Key={'booking_id': booking_id}).get('Item')
    if not booking:
        abort(404)
    return f"<h1>Booking Confirmed</h1><p>Session with tutor {booking['tutor_id']} confirmed.</p>"

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
