from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import boto3
import logging
from datetime import datetime
import uuid
import os
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TutorMatch")

# AWS clients and resources
session = boto3.Session()
sns = session.client('sns', region_name='ap-south-1')
dynamodb = session.resource('dynamodb', region_name='ap-south-1')

# DynamoDB tables
users_table = dynamodb.Table('Users_Table')
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')
tutors_table = dynamodb.Table('Tutors_Table')

# SNS topic ARN
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic'

def ensure_email_subscription(email: str):
    subs = sns.list_subscriptions_by_topic(TopicArn=SNS_TOPIC_ARN)['Subscriptions']
    for s in subs:
        if s['Protocol'] == 'email' and s['Endpoint'] == email:
            if s['SubscriptionArn'] != 'PendingConfirmation':
                return True
            else:
                return False
    res = sns.subscribe(TopicArn=SNS_TOPIC_ARN, Protocol='email', Endpoint=email)
    logger.info(f"Subscription requested, ARN: {res['SubscriptionArn']}")
    return False

def publish_email(subject: str, message: str):
    res = sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    logger.info(f"Published to SNS MessageID: {res['MessageId']}")
    return res['MessageId']

@app.post("/register")
def register(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    if users_table.get_item(Key={'email': email}).get('Item'):
        raise HTTPException(400, "User already exists")
    users_table.put_item(Item={'email': email, 'name': name, 'password': password, 'created_at': datetime.utcnow().isoformat()})
    subscribed = ensure_email_subscription(email)
    if not subscribed:
        logger.info("Please confirm subscription via email before receiving notifications")
    msg = f"Hi {name},\n\nWelcome to TutorMatch!"
    publish_email("Welcome to TutorMatch", msg)
    return RedirectResponse("/login", status_code=302)

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    user = users_table.get_item(Key={'email': email}).get('Item')
    if not user or user['password'] != password:
        raise HTTPException(401, "Invalid credentials")
    return RedirectResponse("/student-dashboard", status_code=302)

@app.post("/book-session/{tutor_id}")
def book_session(tutor_id: str, date: str = Form(...), time: str = Form(...),
                 subject: str = Form(...), email: str = Form(...)):
    tid = str(uuid.uuid4())
    tutor = tutors_table.get_item(Key={'tutor_id': tutor_id}).get('Item', {})
    if 'name' not in tutor:
        raise HTTPException(404, "Tutor not found")
    booking = {
        'booking_id': tid, 'email': email, 'tutor_id': tutor_id,
        'tutor_name': tutor['name'], 'subject': subject,
        'date': date, 'time': time, 'created_at': datetime.utcnow().isoformat(),
        'status': 'pending_payment'
    }
    bookings_table.put_item(Item=booking)
    ensure_email_subscription(email)
    msg = (f"Booking confirmed for {subject} with {tutor['name']} on {date} at {time}.\n"
           f"Booking ID: {tid}")
    publish_email("Booking Confirmed", msg)
    return RedirectResponse(f"/payment?booking_id={tid}", status_code=302)

@app.post("/process-payment")
def process_payment(booking_id: str = Form(...), email: str = Form(...),
                    amount: float = Form(...)):
    pid = str(uuid.uuid4())
    payments_table.put_item(Item={
        'payment_id': pid, 'booking_id': booking_id,
        'email': email, 'amount': amount,
        'status': 'completed', 'created_at': datetime.utcnow().isoformat()
    })
    bookings_table.update_item(
        Key={'booking_id': booking_id},
        UpdateExpression="SET #s = :st, payment_id = :pid",
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':st': 'confirmed', ':pid': pid}
    )
    ensure_email_subscription(email)
    msg = (f"Payment of ${amount:.2f} confirmed for booking {booking_id}.\n"
           "Thank you! Your session is now scheduled.")
    publish_email("Payment Confirmed", msg)
    return JSONResponse({'status': 'ok', 'payment_id': pid})

@app.get("/sns-test/{email}")
def sns_test(email: str):
    ensure_email_subscription(email)
    mid = publish_email("SNS Test from TutorMatch", "This is a test email.")
    return JSONResponse({'message_id': mid})

@app.get("/health")
def health():
    # check SNS and DynamoDB operability quickly
    sns.list_subscriptions_by_topic(TopicArn=SNS_TOPIC_ARN)
    users_table.scan(Limit=1)
    return {'status': 'healthy'}

# (Include other routes & templates as before.)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
