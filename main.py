from flask import Flask, render_template, request, redirect, url_for, abort, jsonify
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
import uuid
import os
import json

app = Flask(__name__)

# AWS Configuration
region = "ap-south-1"
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

users_table = dynamodb.Table("Users_Table")
tutors_table = dynamodb.Table("Tutors_Table")
bookings_table = dynamodb.Table("Bookings_Table")
payments_table = dynamodb.Table("Payments_Table")
SNS_TOPIC_ARN = "arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic"

# Load Tutors
tutors_data = {}
try:
    response = tutors_table.scan()
    tutors_data = {item["tutor_id"]: item for item in response.get("Items", [])}
except Exception as e:
    print(f"Error loading tutors: {e}")

@app.route("/")
def homepage():
    return render_template("homepage.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        name = request.form["name"]

        user_item = {
            "email": email,
            "password": password,
            "name": name,
            "role": "student"
        }
        try:
            users_table.put_item(Item=user_item)
            return redirect(url_for("login"))
        except ClientError as e:
            print("Register error:", e)
            abort(500)
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        try:
            response = users_table.get_item(Key={"email": email})
            user = response.get("Item")
            if user and user["password"] == password:
                return redirect(url_for("dashboard"))
        except ClientError as e:
            print("Login error:", e)
        abort(401)
    return render_template("login.html")

@app.route("/student-dashboard")
def dashboard():
    return render_template("student_dashboard.html")

@app.route("/tutor-search")
def tutor_search():
    return render_template("tutor_search.html", tutors_with_id=[{"id": k, **v} for k, v in tutors_data.items()])

@app.route("/tutor-profile/<tutor_id>")
def tutor_profile(tutor_id):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        abort(404)
    return render_template("tutor_profile.html", tutor=tutor, tutor_id=tutor_id)

@app.route("/book-session/<tutor_id>", methods=["POST"])
def book_session(tutor_id):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        abort(404)

    booking_id = str(uuid.uuid4())
    date = request.form["date"]
    time_ = request.form["time"]
    subject = request.form["subject"]
    session_type = request.form.get("session_type", "Single Session")
    sessions_count = int(request.form.get("sessions_count", 1))
    total_price = float(request.form["total_price"])
    learning_goals = request.form.get("learning_goals", "")
    session_format = request.form.get("session_format", "Online Video Call")

    booking = {
        "booking_id": booking_id,
        "tutor_id": tutor_id,
        "tutor_name": tutor["name"],
        "date": date,
        "time": time_,
        "subject": subject,
        "session_type": session_type,
        "sessions_count": sessions_count,
        "total_price": total_price,
        "learning_goals": learning_goals,
        "session_format": session_format,
        "status": "pending_payment",
        "created_at": datetime.now().isoformat()
    }

    try:
        bookings_table.put_item(Item=booking)
    except ClientError as e:
        print("Booking error:", e)
        abort(500)

    return redirect(url_for("payment", booking_id=booking_id))

@app.route("/payment")
def payment():
    booking_id = request.args.get("booking_id")
    try:
        response = bookings_table.get_item(Key={"booking_id": booking_id})
        booking = response.get("Item")
        if not booking:
            abort(404)
        return render_template("payment.html", booking_id=booking_id, booking=booking)
    except Exception as e:
        print("Payment page error:", e)
        abort(500)

@app.route("/process-payment", methods=["POST"])
def process_payment():
    booking_id = request.form["booking_id"]
    payment_method = request.form["payment_method"]
    card_number = request.form.get("card_number", "")
    cardholder_name = request.form.get("cardholder_name", "")
    email = request.form["email"]
    phone = request.form["phone"]

    try:
        booking_response = bookings_table.get_item(Key={"booking_id": booking_id})
        booking = booking_response.get("Item")
        if not booking:
            abort(404)

        payment_id = str(uuid.uuid4())
        payment_item = {
            "payment_id": payment_id,
            "booking_id": booking_id,
            "amount": booking["total_price"],
            "payment_method": payment_method,
            "status": "completed",
            "created_at": datetime.now().isoformat()
        }

        payments_table.put_item(Item=payment_item)

        bookings_table.update_item(
            Key={"booking_id": booking_id},
            UpdateExpression="SET #s = :status, payment_id = :pid",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": "confirmed", ":pid": payment_id}
        )

        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="New Booking Confirmed",
            Message=f"Booking confirmed for {booking['tutor_name']} on {booking['date']} at {booking['time']}"
        )

        return redirect(url_for("confirmation", booking_id=booking_id))

    except ClientError as e:
        print("Payment error:", e)
        abort(500)

@app.route("/confirmation")
def confirmation():
    booking_id = request.args.get("booking_id")
    try:
        response = bookings_table.get_item(Key={"booking_id": booking_id})
        booking = response.get("Item")
        if not booking:
            abort(404)
        return render_template("confirmation.html", booking_id=booking_id, booking=booking)
    except Exception as e:
        print("Confirmation error:", e)
        abort(500)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "tutors": len(tutors_data)})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
