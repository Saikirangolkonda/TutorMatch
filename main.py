from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from datetime import datetime
import boto3
import uuid
import os
import json

app = FastAPI()

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
sns_client = boto3.client('sns', region_name='ap-south-1')

# DynamoDB Tables
users_table = dynamodb.Table('Users_Table')
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')
tutors_table = dynamodb.Table('Tutors_Table')

# SNS Topic ARN
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/register")
async def register(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    response = users_table.get_item(Key={'email': email})
    if 'Item' in response:
        raise HTTPException(status_code=400, detail="User already exists")
    users_table.put_item(Item={
        'email': email,
        'name': name,
        'password': password,
        'role': 'student'
    })
    return RedirectResponse(url="/login", status_code=302)

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    response = users_table.get_item(Key={'email': email})
    user = response.get('Item')
    if user and user['password'] == password:
        return RedirectResponse(url="/student-dashboard", status_code=302)
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/book-session/{tutor_id}")
async def book_session(tutor_id: str, date: str = Form(...), time: str = Form(...), subject: str = Form(...), email: str = Form(...)):
    booking_id = str(uuid.uuid4())
    tutor_response = tutors_table.get_item(Key={'tutor_id': tutor_id})
    tutor = tutor_response.get('Item', {})
    booking = {
        'booking_id': booking_id,
        'email': email,
        'tutor_id': tutor_id,
        'tutor_name': tutor.get('name', ''),
        'date': date,
        'time': time,
        'subject': subject,
        'status': 'pending_payment',
        'created_at': datetime.now().isoformat()
    }
    bookings_table.put_item(Item=booking)
    return RedirectResponse(url="/payment", status_code=302)

@app.post("/process-payment")
async def process_payment(booking_id: str = Form(...), email: str = Form(...), amount: float = Form(...)):
    payment_id = str(uuid.uuid4())
    payments_table.put_item(Item={
        'payment_id': payment_id,
        'booking_id': booking_id,
        'amount': amount,
        'status': 'completed',
        'created_at': datetime.now().isoformat()
    })
    bookings_table.update_item(
        Key={'booking_id': booking_id},
        UpdateExpression="SET #s = :status, payment_id = :pid",
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':status': 'confirmed', ':pid': payment_id}
    )
    # Fetch booking and tutor details for notification
    booking = bookings_table.get_item(Key={'booking_id': booking_id}).get('Item', {})
    tutor_response = tutors_table.get_item(Key={'tutor_id': booking.get('tutor_id')})
    tutor = tutor_response.get('Item', {})
    message = f"""https://github.com/Saikirangolkonda/TutorMatch/blob/main/main.py
    Your upcoming session is confirmed!
    Tutor: {tutor.get('name')}
    Subjects: {', '.join(tutor.get('subjects', []))}
    Date: {booking.get('date')}
    Time: {booking.get('time')}
    Rate: {tutor.get('rate', 'N/A')}
    Bio: {tutor.get('bio', '')}
    """
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Message=message.strip(),
        Subject="Upcoming Session Confirmation",
        MessageAttributes={
            'email': {'DataType': 'String', 'StringValue': email}
        }
    )
    return JSONResponse(content={"message": "Payment processed and session notification sent."})

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
