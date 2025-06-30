# main.py

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
import boto3
import uuid
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

session = boto3.Session()
dynamodb = session.resource('dynamodb', region_name='ap-south-1')
sns_client = session.client('sns', region_name='ap-south-1')

users_table = dynamodb.Table('Users_Table')
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')
tutors_table = dynamodb.Table('Tutors_Table')

SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic'

async def send_sns_email(email: str, subject: str, message: str):
    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject
        )
        logger.info(f"Email sent to {email}")
    except Exception as e:
        logger.error(f"Error sending email: {e}")

@app.post("/process-payment")
async def process_payment(
    booking_id: str = Form(...),
    email: str = Form(...),
    amount: float = Form(...)
):
    try:
        payment_id = str(uuid.uuid4())
        
        booking_resp = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = booking_resp.get('Item', {})
        tutor_resp = tutors_table.get_item(Key={'tutor_id': booking.get('tutor_id', '')})
        tutor = tutor_resp.get('Item', {})
        
        payments_table.put_item(Item={
            'payment_id': payment_id,
            'booking_id': booking_id,
            'email': email,
            'amount': amount,
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        })
        
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="SET #s = :status",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':status': 'confirmed'}
        )
        
        session_message = f"""
Hello {booking.get('email')},

Your session has been confirmed!

Session Details:
Tutor: {tutor.get('name', 'N/A')}
Subject: {booking.get('subject', 'N/A')}
Date: {booking.get('date', 'N/A')}
Time: {booking.get('time', 'N/A')}

Thank you for booking with us!

The TutorMatch Team
"""
        await send_sns_email(email, "Your Session is Confirmed!", session_message)
        
        return JSONResponse(content={"message": "Payment processed and session confirmed notification sent."})
        
    except Exception as e:
        logger.error(f"Error processing payment: {e}")
        raise HTTPException(status_code=500, detail="Error processing payment")
