from flask import Flask, request, jsonify, abort
import boto3
import uuid
from datetime import datetime

app = Flask(__name__)

# AWS Setup
region_name = 'ap-south-1'
dynamodb = boto3.resource('dynamodb', region_name=region_name)
sns = boto3.client('sns', region_name=region_name)
sns_topic_arn = "arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic"

# DynamoDB Tables
bookings_table = dynamodb.Table("Bookings_Table")
payments_table = dynamodb.Table("Payments_Table")
tutors_table = dynamodb.Table("Tutors_Table")
users_table = dynamodb.Table("Users_Table")

# User registration
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    name = data.get("name")

    existing = users_table.get_item(Key={"email": email})
    if "Item" in existing:
        return jsonify({"error": "User already exists"}), 400

    users_table.put_item(Item={
        "email": email,
        "password": password,
        "name": name,
        "role": "student"
    })
    return jsonify({"message": "User registered successfully"})

# User login
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = users_table.get_item(Key={"email": email}).get("Item")
    if not user or user["password"] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    return jsonify({"message": "Login successful"})

# Get tutors list
@app.route("/tutors", methods=["GET"])
def list_tutors():
    result = tutors_table.scan()
    return jsonify(result.get("Items", []))

# Book session
@app.route("/book-session", methods=["POST"])
def book_session():
    data = request.json
    tutor_id = data.get("tutor_id")

    tutor = tutors_table.get_item(Key={"tutor_id": tutor_id}).get("Item")
    if not tutor:
        return jsonify({"error": "Tutor not found"}), 404

    booking_id = str(uuid.uuid4())
    sessions_count = int(data.get("sessions_count", 1))
    total_price = tutor["rate"] * sessions_count

    booking = {
        "booking_id": booking_id,
        "tutor_id": tutor_id,
        "date": data.get("date"),
        "time": data.get("time"),
        "subject": data.get("subject"),
        "session_type": data.get("session_type", "Single Session"),
        "sessions_count": sessions_count,
        "learning_goals": data.get("learning_goals", ""),
        "session_format": data.get("session_format", "Online Video Call"),
        "total_price": total_price,
        "status": "pending_payment",
        "created_at": datetime.now().isoformat()
    }

    bookings_table.put_item(Item=booking)
    return jsonify({"message": "Booking created", "booking_id": booking_id})

# Process payment
@app.route("/process-payment", methods=["POST"])
def process_payment():
    data = request.json
    booking_id = data.get("booking_id")
    booking = bookings_table.get_item(Key={"booking_id": booking_id}).get("Item")

    if not booking:
        return jsonify({"error": "Booking not found"}), 404

    payment_id = str(uuid.uuid4())

    payments_table.put_item(Item={
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "payment_method": data.get("payment_method"),
        "status": "completed",
        "created_at": datetime.now().isoformat()
    })

    bookings_table.update_item(
        Key={"booking_id": booking_id},
        UpdateExpression="SET #s = :status, payment_id = :payment_id",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "confirmed", ":payment_id": payment_id}
    )

    sns.publish(
        TopicArn=sns_topic_arn,
        Subject="Booking Confirmed",
        Message=f"Your session on {booking['subject']} with tutor {booking['tutor_id']} is confirmed for {booking['date']} at {booking['time']}."
    )

    return jsonify({"message": "Payment successful", "booking_id": booking_id})

# Get all bookings (for testing)
@app.route("/bookings", methods=["GET"])
def list_bookings():
    result = bookings_table.scan()
    return jsonify(result.get("Items", []))

# Health check
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
