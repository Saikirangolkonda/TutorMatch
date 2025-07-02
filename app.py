from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime, timedelta
from decimal import Decimal
import boto3, os, json, uuid

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS setup
region_name = 'ap-south-1'
dynamodb = boto3.resource('dynamodb', region_name=region_name)
sns = boto3.client('sns', region_name=region_name)
sns_topic_arn = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# DynamoDB Tables
users_table = dynamodb.Table('Users')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')
sessions_table = dynamodb.Table('Sessions')

# Load static tutor data from JSON
tutors_file = os.path.join("templates", "tutors_data.json")
with open(tutors_file) as f:
    tutors_data = json.load(f)

@app.route('/')
def homepage():
    return render_template("homepage.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = users_table.get_item(Key={'email': email}).get('Item')
            if user and user['password'] == password:
                return redirect(url_for('student_dashboard', student_email=email))
        except Exception as e:
            print(f"Login Error: {e}")
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
            print(f"DynamoDB Register Error: {e}")
            return "Error registering user", 500
    return render_template("register.html")

@app.route('/student-dashboard')
def student_dashboard():
    return render_template("student_dashboard.html")

@app.route('/tutor-search')
def tutor_search():
    return render_template("tutor_search.html", tutors_with_id=[{"id": k, **v} for k, v in tutors_data.items()])

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
        try:
            booking_id = str(uuid.uuid4())
            date = request.form['date']
            time = request.form['time']
            subject = request.form['subject']
            session_type = request.form.get('session_type', 'Single Session')
            sessions_count = int(request.form.get('sessions_count', 1))
            total_price = Decimal(str(tutor['rate'])) * sessions_count
            learning_goals = request.form.get('learning_goals', '')
            session_format = request.form.get('session_format', 'Online Video Call')

            booking_item = {
                "booking_id": booking_id,
                "tutor_id": tutor_id,
                "date": date,
                "time": time,
                "subject": subject,
                "session_type": session_type,
                "sessions_count": sessions_count,
                "total_price": str(total_price),
                "learning_goals": learning_goals,
                "session_format": session_format,
                "status": "pending_payment",
                "tutor_name": tutor['name'],
                "created_at": datetime.utcnow().isoformat()
            }
            bookings_table.put_item(Item=booking_item)
            return redirect(url_for("payment", booking_id=booking_id))
        except Exception as e:
            print(f"Booking Error: {e}")
            abort(500)
    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    try:
        booking_id = request.args.get('booking_id')
        booking = bookings_table.get_item(Key={"booking_id": booking_id}).get("Item")
        if not booking:
            abort(404)
        return render_template("payment.html", booking=booking, booking_id=booking_id)
    except Exception as e:
        print(f"Payment Load Error: {e}")
        abort(500)

@app.route('/process-payment', methods=['POST'])
def process_payment():
    try:
        booking_id = request.form['booking_id']
        payment_method = request.form['payment_method']
        email = request.form['email']
        phone = request.form['phone']
        booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item')
        if not booking:
            abort(404)

        payment_id = str(uuid.uuid4())
        payments_table.put_item(Item={
            "payment_id": payment_id,
            "booking_id": booking_id,
            "amount": booking['total_price'],
            "payment_method": payment_method,
            "status": "completed",
            "created_at": datetime.utcnow().isoformat()
        })

        # Update booking with payment info
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="SET #s = :s, payment_id = :p",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "confirmed", ":p": payment_id}
        )

        # Send notification
        sns.publish(
            TopicArn=sns_topic_arn,
            Message=f"Session with {booking['tutor_name']} is confirmed on {booking['date']} at {booking['time']}.",
            Subject="TutorMatch - Session Confirmed"
        )

        return redirect(url_for('confirmation', booking_id=booking_id))
    except Exception as e:
        print(f"Payment Error: {e}")
        abort(500)

@app.route('/confirmation')
def confirmation():
    try:
        booking_id = request.args.get('booking_id')
        booking = bookings_table.get_item(Key={"booking_id": booking_id}).get("Item")
        if not booking:
            abort(404)
        return render_template("confirmation.html", booking=booking)
    except Exception as e:
        print(f"Confirmation Load Error: {e}")
        abort(500)

@app.route('/api/student-data')
def student_data():
    email = request.args.get("student_email")
    try:
        response = bookings_table.scan()
        items = response.get("Items", [])
        bookings_list = []
        payments_list = []
        notifications = []

        for b in items:
            if 'tutor_name' not in b:
                continue
            bookings_list.append({
                "id": b["booking_id"],
                "tutor_name": b["tutor_name"],
                "subject": b["subject"],
                "date": b["date"],
                "time": b["time"],
                "status": b["status"],
                "total_price": b["total_price"],
                "session_format": b["session_format"],
                "created_at": b["created_at"]
            })
            if "payment_id" in b:
                pay = payments_table.get_item(Key={"payment_id": b["payment_id"]}).get("Item")
                if pay:
                    payments_list.append({
                        "id": pay["payment_id"],
                        "amount": pay["amount"],
                        "status": pay["status"],
                        "method": pay["payment_method"],
                        "date": pay["created_at"]
                    })
            if b["status"] == "confirmed":
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your session with {b['tutor_name']} is confirmed.",
                    "date": datetime.utcnow().strftime("%Y-%m-%d")
                })

        return jsonify({
            "bookings": bookings_list,
            "payments": payments_list,
            "notifications": notifications
        })
    except Exception as e:
        print(f"Data API Error: {e}")
        return jsonify({"error": "Could not load data"}), 500

@app.route('/logout')
def logout():
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "tutors_count": len(tutors_data)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
