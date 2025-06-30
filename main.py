from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import boto3
from botocore.exceptions import ClientError
from datetime import datetime
import uuid
import logging

# Setup
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS
session = boto3.Session()
dynamodb = session.resource('dynamodb', region_name='ap-south-1')
sns = session.client('sns', region_name='ap-south-1')

USERS_TABLE = dynamodb.Table('Users_Table')
BOOKINGS_TABLE = dynamodb.Table('Bookings_Table')
PAYMENTS_TABLE = dynamodb.Table('Payments_Table')
TUTORS_TABLE = dynamodb.Table('Tutors_Table')
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic'

# Helpers
async def send_email(subject, message):
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Message=message, Subject=subject)
        logger.info("SNS publish successful")
    except ClientError as e:
        logger.error(f"SNS publish error: {e}")
        raise

# Routes
@app.post("/register")
async def register(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    try:
        resp = USERS_TABLE.get_item(Key={'email': email})
        if 'Item' in resp:
            raise HTTPException(status_code=400, detail="User already exists")

        USERS_TABLE.put_item(Item={
            'email': email,
            'name': name,
            'password': password,
            'created_at': datetime.now().isoformat()
        })

        msg = f"Hello {name}, welcome to TutorMatch! Your account with email {email} has been created."
        await send_email("Welcome to TutorMatch", msg)
        return RedirectResponse(url="/login?registered=true", status_code=302)
    except Exception as e:
        logger.error(f"Register error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    try:
        resp = USERS_TABLE.get_item(Key={'email': email})
        user = resp.get('Item')
        if user and user['password'] == password:
            return RedirectResponse(url="/student-dashboard", status_code=302)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

@app.post("/book-session/{tutor_id}")
async def book_session(tutor_id: str, date: str = Form(...), time: str = Form(...), subject: str = Form(...), email: str = Form(...)):
    try:
        booking_id = str(uuid.uuid4())
        tutor_resp = TUTORS_TABLE.get_item(Key={'tutor_id': tutor_id})
        tutor = tutor_resp.get('Item', {})
        tutor_name = tutor.get('name', 'Unknown')

        BOOKINGS_TABLE.put_item(Item={
            'booking_id': booking_id,
            'email': email,
            'tutor_id': tutor_id,
            'date': date,
            'time': time,
            'subject': subject,
            'status': 'pending_payment',
            'created_at': datetime.now().isoformat()
        })

        msg = f"Session booked with {tutor_name} on {date} at {time}.\nSubject: {subject}\nBooking ID: {booking_id}\nProceed to payment to confirm."
        await send_email("Booking Confirmation", msg)

        return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)
    except Exception as e:
        logger.error(f"Booking error: {e}")
        raise HTTPException(status_code=500, detail="Booking failed")

@app.post("/process-payment")
async def process_payment(booking_id: str = Form(...), email: str = Form(...), amount: float = Form(...)):
    try:
        payment_id = str(uuid.uuid4())
        PAYMENTS_TABLE.put_item(Item={
            'payment_id': payment_id,
            'booking_id': booking_id,
            'email': email,
            'amount': amount,
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        })

        BOOKINGS_TABLE.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="SET #s = :s, payment_id = :p",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'confirmed', ':p': payment_id}
        )

        booking_resp = BOOKINGS_TABLE.get_item(Key={'booking_id': booking_id})
        booking = booking_resp.get('Item', {})
        tutor_name = booking.get('tutor_name', 'N/A')
        subject = booking.get('subject', 'N/A')
        date = booking.get('date', 'N/A')
        time_slot = booking.get('time', 'N/A')

        msg = f"Payment of ${amount:.2f} received.\nSession confirmed with {tutor_name} on {date} at {time_slot}.\nBooking ID: {booking_id}\nPayment ID: {payment_id}"
        await send_email("Payment Confirmation & Session Details", msg)

        return JSONResponse({"status": "success", "payment_id": payment_id})
    except Exception as e:
        logger.error(f"Payment error: {e}")
        raise HTTPException(status_code=500, detail="Payment failed")

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
