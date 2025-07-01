from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from boto3 import client, resource
from datetime import datetime, timedelta
import uuid
import os

app = FastAPI(title="TutorMatch", description="Connect students with tutors")

# DynamoDB setup
dynamodb = resource('dynamodb', region_name='ap-south-1')
bookings_table = dynamodb.Table("Bookings_Table")
payments_table = dynamodb.Table("Payments_Table")
tutors_table = dynamodb.Table("Tutors_Table")
users_table = dynamodb.Table("Users_Table")

# SNS setup
sns = client('sns', region_name='ap-south-1')
sns_topic_arn = "arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic"

# Data models
class User(BaseModel):
    email: str
    password: str
    name: str

class BookingRequest(BaseModel):
    tutor_id: str
    date: str
    time: str
    subject: str
    session_type: str = "Single Session"
    sessions_count: int = 1
    learning_goals: str = ""
    session_format: str = "Online Video Call"

class PaymentRequest(BaseModel):
    booking_id: str
    payment_method: str
    email: str
    phone: str

# Register user
@app.post("/register")
async def register_user(user: User):
    response = users_table.get_item(Key={"email": user.email})
    if "Item" in response:
        raise HTTPException(status_code=400, detail="User already exists")
    users_table.put_item(Item=user.dict())
    return {"message": "User registered successfully"}

# Login user (simple validation)
@app.post("/login")
async def login_user(user: User):
    response = users_table.get_item(Key={"email": user.email})
    if "Item" not in response or response["Item"]["password"] != user.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "Login successful"}

# List tutors
@app.get("/tutors")
async def list_tutors():
    response = tutors_table.scan()
    return response.get("Items", [])

# Book session
@app.post("/book-session")
async def book_session(booking: BookingRequest):
    tutor = tutors_table.get_item(Key={"tutor_id": booking.tutor_id}).get("Item")
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")

    booking_id = str(uuid.uuid4())
    total_price = tutor["rate"] * booking.sessions_count

    item = booking.dict()
    item.update({
        "booking_id": booking_id,
        "total_price": total_price,
        "status": "pending_payment",
        "created_at": datetime.now().isoformat()
    })

    bookings_table.put_item(Item=item)
    return {"message": "Booking created", "booking_id": booking_id}

# Payment route
@app.post("/process-payment")
async def process_payment(payment: PaymentRequest):
    booking_response = bookings_table.get_item(Key={"booking_id": payment.booking_id})
    if "Item" not in booking_response:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    booking = booking_response["Item"]
    payment_id = str(uuid.uuid4())

    payments_table.put_item(Item={
        "payment_id": payment_id,
        "booking_id": booking["booking_id"],
        "amount": booking["total_price"],
        "payment_method": payment.payment_method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    })

    # Update booking status
    bookings_table.update_item(
        Key={"booking_id": booking["booking_id"]},
        UpdateExpression="SET #s = :s, payment_id = :p",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "confirmed", ":p": payment_id}
    )

    # Send SNS notification
    sns.publish(
        TopicArn=sns_topic_arn,
        Subject="Booking Confirmed",
        Message=f"Your session on {booking['subject']} is confirmed with tutor {booking['tutor_id']} on {booking['date']} at {booking['time']}."
    )

    return {"message": "Payment processed & booking confirmed", "booking_id": booking["booking_id"]}

# View all bookings (for testing)
@app.get("/bookings")
async def list_bookings():
    return bookings_table.scan().get("Items", [])

# Health check
@app.get("/health")
async def health():
    return {"status": "healthy"}
