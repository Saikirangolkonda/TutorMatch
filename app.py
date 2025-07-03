from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from datetime import datetime
import os, json, uuid, boto3

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# AWS Clients
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
sns = boto3.client('sns', region_name='ap-south-1')
sns_topic_arn = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# DynamoDB Tables
tutors_table = dynamodb.Table('Tutors')
bookings_table = dynamodb.Table('Bookings')
payments_table = dynamodb.Table('Payments')

# Load local tutor data
TUTORS_FILE = os.path.join("templates", "tutors_data.json")
if os.path.exists(TUTORS_FILE):
    with open(TUTORS_FILE) as f:
        tutors_data = json.load(f)
else:
    tutors_data = {}
    os.makedirs("templates", exist_ok=True)
    with open(TUTORS_FILE, "w") as f:
        json.dump(tutors_data, f)

users = {}

@app.route('/')
def homepage():
    return render_template("homepage.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in users and users[email]['password'] == password:
            return redirect(url_for('student_dashboard'))
        return "Invalid credentials", 401
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        if email in users:
            return "User already exists", 400
        users[email] = {"email": email, "password": password, "name": name}
        return redirect(url_for('login'))
    return render_template('register.html')

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

    # ✅ Store tutor data in DynamoDB if not already present
    try:
        response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        if 'Item' not in response:
            tutors_table.put_item(Item={
                'tutor_id': tutor_id,
                'name': tutor['name'],
                'subjects': tutor['subjects'],
                'rate': tutor['rate'],
                'rating': tutor['rating'],
                'bio': tutor['bio'],
                'availability': tutor['availability']
            })
            print(f"✅ Tutor {tutor['name']} stored in DynamoDB.")
    except Exception as e:
        print(f"⚠️ Error storing tutor to DynamoDB: {e}")

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

        # ✅ Save booking in DynamoDB
        bookings_table.put_item(Item={
            "booking_id": booking_id,
            "tutor_id": tutor_id,
            "tutor_name": tutor["name"],
            "subject": subject,
            "date": date,
            "time": time,
            "status": "pending_payment",
            "session_type": session_type,
            "sessions_count": sessions_count,
            "total_price": total_price,
            "learning_goals": learning_goals,
            "session_format": session_format,
            "created_at": datetime.now().isoformat()
        })

        return redirect(url_for("payment", booking_id=booking_id))

    return render_template("booksession.html", tutor=tutor, tutor_id=tutor_id)

@app.route('/payment')
def payment():
    booking_id = request.args.get('booking_id')

    # ✅ Fetch full booking object from DynamoDB
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            abort(404)
    except Exception as e:
        print(f"❌ Error fetching booking: {e}")
        abort(500)

    return render_template("payment.html", booking=booking, booking_id=booking_id)


    payment_id = str(uuid.uuid4())
    payments_table.put_item(Item={
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "payment_method": payment_method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    })

    # ✅ Update booking status
    bookings_table.update_item(
        Key={'booking_id': booking_id},
        UpdateExpression="SET #s = :val, payment_id = :pid",
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':val': 'confirmed', ':pid': payment_id}
    )

    # ✅ Send email via SNS
    try:
        sns.publish(
            TopicArn=sns_topic_arn,
            Subject="📚 Session Confirmed",
            Message=f"Your session with {booking['tutor_name']} on {booking['date']} at {booking['time']} is confirmed."
        )
        print("✅ SNS Email Notification Sent")
    except Exception as e:
        print(f"⚠️ SNS Error: {e}")

    return redirect(url_for('confirmation', booking_id=booking_id))

@app.route('/confirmation')
def confirmation():
    booking_id = request.args.get('booking_id')
    return render_template("confirmation.html", booking={"id": booking_id})

@app.route('/logout')
def logout():
    return redirect(url_for("homepage"))

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "tutors_count": len(tutors_data)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
