from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime
import boto3
import uuid
import os
import json
import uvicorn

app = FastAPI(title="TutorMatch", description="Connect students with tutors")

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
sns_client = boto3.client('sns', region_name='ap-south-1')

# DynamoDB Tables
users_table = dynamodb.Table('Users_Table')
tutors_table = dynamodb.Table('Tutors_Table')
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')

# SNS Topic ARN
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

# Templates & static files
templates = Jinja2Templates(directory="templates")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/register")
async def register(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    resp = users_table.get_item(Key={'email': email})
    if 'Item' in resp:
        raise HTTPException(status_code=400, detail="User already exists")
    users_table.put_item(Item={'email': email, 'name': name, 'password': password, 'role': 'student'})
    return RedirectResponse(url="/login", status_code=302)

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    resp = users_table.get_item(Key={'email': email})
    user = resp.get('Item')
    if user and user['password'] == password:
        return RedirectResponse(url="/student-dashboard", status_code=302)
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/book-session/{tutor_id}")
async def book_session(tutor_id: str,
                       date: str = Form(...),
                       time: str = Form(...),
                       subject: str = Form(...),
                       email: str = Form(...)):
    booking_id = str(uuid.uuid4())
    tutor_resp = tutors_table.get_item(Key={'tutor_id': tutor_id})
    tutor = tutor_resp.get('Item', {})
    booking = {
        'booking_id': booking_id,
        'email': email,
        'tutor_id': tutor_id,
        'tutor_name': tutor.get('name', 'Unknown'),
        'date': date,
        'time': time,
        'subject': subject,
        'status': 'pending_payment',
        'created_at': datetime.utcnow().isoformat()
    }
    bookings_table.put_item(Item=booking)
    return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)

@app.post("/process-payment")
async def process_payment(booking_id: str = Form(...),
                          payment_method: str = Form(...),
                          card_number: str = Form(""),
                          cardholder_name: str = Form(""),
                          email: str = Form(...),
                          phone: str = Form(...)):
    # Record payment
    payment_id = str(uuid.uuid4())
    amount = float(bookings_table.get_item(Key={'booking_id': booking_id})
                   .get('Item', {}).get('subject', 0))  # ensure amount is calculated
    payments_table.put_item(Item={'payment_id': payment_id,
                                 'booking_id': booking_id,
                                 'amount': amount,
                                 'payment_method': payment_method,
                                 'status': 'completed',
                                 'created_at': datetime.utcnow().isoformat()})

    # Update booking
    bookings_table.update_item(
        Key={'booking_id': booking_id},
        UpdateExpression="SET #st = :c, payment_id = :p",
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':c': 'confirmed', ':p': payment_id}
    )

    # Fetch updated booking & tutor details
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item', {})
    tutor = tutors_table.get_item(Key={'tutor_id': booking.get('tutor_id')}).get('Item', {})

    msg = f"""Your session is confirmed!
Tutor: {tutor.get('name')}
Subject: {booking.get('subject')}
Date & Time: {booking.get('date')} at {booking.get('time')}
Rate: ${tutor.get('rate', 'N/A')}"""

    # Send SNS notification (goes to your confirmed email subscription)
    sns_client.publish(TopicArn=SNS_TOPIC_ARN, Subject="Upcoming Tutor Session", Message=msg)

    return JSONResponse(content={"message": "Payment processed and notification sent."})

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
