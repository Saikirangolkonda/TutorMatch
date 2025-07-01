from flask import Flask, request, jsonify, abort
from datetime import datetime
import uuid
import boto3
import os

# AWS Clients
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
sns = boto3.client('sns', region_name='ap-south-1')

# Tables
users_table = dynamodb.Table('Users_Table')
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')
tutors_table = dynamodb.Table('Tutors_Table')

# SNS Topic ARN (update if needed)
SNS_TOPIC_ARN = "arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic"

app = Flask(__name__)

@app.route("/")
def homepage():
    return jsonify({"message": "Welcome to TutorMatch on AWS!"})

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    email = data.get("email")
    if not email:
        return abort(400, "Missing email")
    user = {
        "email": email,
        "name": data.get("name", ""),
        "password": data.get("password", ""),
        "role": "student",
        "created_at": datetime.utcnow().isoformat()
    }
    users_table.put_item(Item=user)
    return jsonify({"message": "User registered successfully", "user": user})

@app.route("/book-session", methods=["POST"])
def book_session():
    data = request.json
    tutor_id = data.get("tutor_id")
    tutor_resp = tutors_table.get_item(Key={"tutor_id": tutor_id})
    tutor_data = tutor_resp.get("Item")
    if not tutor_data:
        return abort(404, "Tutor not found")

    sessions_count = int(data.get("sessions_count", 1))
    booking_id = str(uuid.uuid4())
    total_price = tutor_data["rate"] * sessions_count

    booking = {
        "booking_id": booking_id,
        "tutor_id": tutor_id,
        "student_email": data.get("student_email"),
        "subject": data.get("subject"),
        "date": data.get("date"),
        "time": data.get("time"),
        "sessions_count": sessions_count,
        "session_type": data.get("session_type", "Single Session"),
        "session_format": data.get("session_format", "Online"),
        "learning_goals": data.get("learning_goals", ""),
        "total_price": total_price,
        "status": "pending_payment",
        "created_at": datetime.utcnow().isoformat()
    }

    bookings_table.put_item(Item=booking)
    return jsonify({"message": "Session booked", "booking_id": booking_id})

@app.route("/process-payment", methods=["POST"])
def process_payment():
    data = request.json
    booking_id = data.get("booking_id")

    resp = bookings_table.get_item(Key={"booking_id": booking_id})
    booking = resp.get("Item")
    if not booking:
        return abort(404, "Booking not found")

    payment_id = str(uuid.uuid4())
    payment = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "status": "completed",
        "payment_method": data.get("payment_method"),
        "created_at": datetime.utcnow().isoformat()
    }
    payments_table.put_item(Item=payment)

    # Update booking
    bookings_table.update_item(
        Key={"booking_id": booking_id},
        UpdateExpression="SET #s = :s, payment_id = :p",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "confirmed", ":p": payment_id}
    )

    # Notify via SNS
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Message=f"Booking Confirmed: {booking_id} for {booking['student_email']} with tutor {booking['tutor_id']}",
        Subject="TutorMatch Booking Confirmation"
    )

    return jsonify({"message": "Payment processed", "payment_id": payment_id})

@app.route("/bookings", methods=["GET"])
def get_bookings():
    scan = bookings_table.scan()
    return jsonify(scan.get("Items", []))

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
