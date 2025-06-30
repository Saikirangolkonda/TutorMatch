from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
import boto3
import os
import uuid
import json
import logging
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# AWS clients with error handling
try:
    dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
    sns_client = boto3.client('sns', region_name='ap-south-1')
    logger.info("AWS clients initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize AWS clients: {e}")
    raise

# DynamoDB Tables
users_table = dynamodb.Table('Users_Table')
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')
tutors_table = dynamodb.Table('Tutors_Table')

# SNS Topic ARN
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorMatchNotifications'

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Helper function to subscribe email to SNS topic
async def subscribe_email_to_sns(email: str):
    """Subscribe an email address to the SNS topic if not already subscribed"""
    try:
        # Check if email is already subscribed
        response = sns_client.list_subscriptions_by_topic(TopicArn=SNS_TOPIC_ARN)
        existing_emails = [
            sub['Endpoint'] for sub in response['Subscriptions'] 
            if sub['Protocol'] == 'email' and sub['Endpoint'] == email
        ]
        
        if not existing_emails:
            # Subscribe the email
            subscription_response = sns_client.subscribe(
                TopicArn=SNS_TOPIC_ARN,
                Protocol='email',
                Endpoint=email
            )
            logger.info(f"Email {email} subscribed to SNS topic")
            return subscription_response['SubscriptionArn']
        else:
            logger.info(f"Email {email} already subscribed to SNS topic")
            return existing_emails[0]
            
    except ClientError as e:
        logger.error(f"Error subscribing email to SNS: {e}")
        return None

# Helper function to send SNS notification
async def send_sns_notification(email: str, subject: str, message: str):
    """Send SNS notification with proper error handling"""
    try:
        # First ensure the email is subscribed
        await subscribe_email_to_sns(email)
        
        # Send the notification
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject,
            MessageAttributes={
                'email': {
                    'DataType': 'String',
                    'StringValue': email
                }
            }
        )
        logger.info(f"SNS notification sent successfully to {email}")
        return response['MessageId']
        
    except ClientError as e:
        logger.error(f"Error sending SNS notification to {email}: {e}")
        return None

@app.post("/register")
async def register(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):
    try:
        # Check if user already exists
        response = users_table.get_item(Key={'email': email})
        if 'Item' in response:
            raise HTTPException(status_code=400, detail="User already exists")

        # Create new user
        users_table.put_item(Item={
            'email': email,
            'name': name,
            'password': password,  # In production, hash this password!
            'role': 'student',
            'created_at': datetime.now().isoformat()
        })

        # Send welcome email using SNS
        welcome_message = f"""
Hello {name},

Welcome to TutorMatch! Your account has been successfully created.

You can now log in and start booking tutoring sessions with our qualified tutors.

Best regards,
The TutorMatch Team
        """.strip()

        message_id = await send_sns_notification(
            email=email,
            subject="Welcome to TutorMatch",
            message=welcome_message
        )

        if message_id:
            logger.info(f"Welcome email sent to {email} with message ID: {message_id}")
        else:
            logger.warning(f"Failed to send welcome email to {email}")

        return RedirectResponse(url="/login", status_code=302)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during registration: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    try:
        response = users_table.get_item(Key={'email': email})
        user = response.get('Item')

        if user and user['password'] == password:
            # In a real app, you'd create a JWT token here
            return RedirectResponse(url="/student-dashboard", status_code=302)

        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

@app.post("/book-session/{tutor_id}")
async def book_session(
    tutor_id: str,
    date: str = Form(...),
    time: str = Form(...),
    subject: str = Form(...),
    email: str = Form(...)
):
    try:
        booking_id = str(uuid.uuid4())
        
        # Get tutor information
        tutor_response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        tutor = tutor_response.get('Item', {})
        tutor_name = tutor.get('name', 'Unknown Tutor')

        # Create booking
        booking = {
            'booking_id': booking_id,
            'email': email,
            'tutor_id': tutor_id,
            'tutor_name': tutor_name,
            'date': date,
            'time': time,
            'subject': subject,
            'status': 'pending_payment',
            'created_at': datetime.now().isoformat()
        }

        bookings_table.put_item(Item=booking)

        # Send booking confirmation using SNS
        booking_message = f"""
Hello,

Your tutoring session has been successfully booked!

Session Details:
- Tutor: {tutor_name}
- Subject: {subject}
- Date: {date}
- Time: {time}
- Booking ID: {booking_id}

Please proceed to payment to confirm your session.

Best regards,
The TutorMatch Team
        """.strip()

        message_id = await send_sns_notification(
            email=email,
            subject="Session Booking Confirmation - TutorMatch",
            message=booking_message
        )

        if message_id:
            logger.info(f"Booking confirmation sent to {email} with message ID: {message_id}")
        else:
            logger.warning(f"Failed to send booking confirmation to {email}")

        return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)
        
    except Exception as e:
        logger.error(f"Error during session booking: {e}")
        raise HTTPException(status_code=500, detail="Booking failed")

@app.post("/process-payment")
async def process_payment(
    booking_id: str = Form(...),
    email: str = Form(...),
    amount: float = Form(...)
):
    try:
        payment_id = str(uuid.uuid4())
        
        # Create payment record
        payment = {
            'payment_id': payment_id,
            'booking_id': booking_id,
            'email': email,
            'amount': amount,
            'status': 'completed',
            'created_at': datetime.now().isoformat()
        }

        payments_table.put_item(Item=payment)

        # Get booking details for the confirmation message
        booking_response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = booking_response.get('Item', {})

        # Update booking status
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="SET #s = :status, payment_id = :pid",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':status': 'confirmed', ':pid': payment_id}
        )

        # Send payment confirmation using SNS
        payment_message = f"""
Hello,

Your payment has been successfully processed!

Payment Details:
- Amount: ${amount:.2f}
- Payment ID: {payment_id}
- Booking ID: {booking_id}

Session Details:
- Tutor: {booking.get('tutor_name', 'N/A')}
- Subject: {booking.get('subject', 'N/A')}
- Date: {booking.get('date', 'N/A')}
- Time: {booking.get('time', 'N/A')}

Your session is now confirmed. Please check your dashboard for further details.

Best regards,
The TutorMatch Team
        """.strip()

        message_id = await send_sns_notification(
            email=email,
            subject="Payment Confirmation - TutorMatch",
            message=payment_message
        )

        if message_id:
            logger.info(f"Payment confirmation sent to {email} with message ID: {message_id}")
            return JSONResponse(content={
                "message": "Payment processed and confirmation sent.",
                "payment_id": payment_id,
                "notification_sent": True
            })
        else:
            logger.warning(f"Payment processed but failed to send confirmation to {email}")
            return JSONResponse(content={
                "message": "Payment processed but notification failed.",
                "payment_id": payment_id,
                "notification_sent": False
            })
            
    except Exception as e:
        logger.error(f"Error during payment processing: {e}")
        raise HTTPException(status_code=500, detail="Payment processing failed")

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        # Test DynamoDB connection
        users_table.scan(Limit=1)
        
        # Test SNS connection
        sns_client.get_topic_attributes(TopicArn=SNS_TOPIC_ARN)
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "dynamodb": "connected",
                "sns": "connected"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

@app.get("/test-sns/{email}")
async def test_sns(email: str):
    """Test endpoint to verify SNS functionality"""
    message_id = await send_sns_notification(
        email=email,
        subject="TutorMatch - Test Email",
        message="This is a test email to verify SNS functionality is working correctly."
    )
    
    if message_id:
        return JSONResponse(content={
            "message": "Test email sent successfully",
            "message_id": message_id,
            "email": email
        })
    else:
        raise HTTPException(status_code=500, detail="Failed to send test email")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
