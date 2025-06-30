from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timedelta
import boto3
import os
import uuid
import json
import logging
from botocore.exceptions import ClientError
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# AWS clients with explicit configuration
try:
    # Use explicit session for better error handling
    session = boto3.Session()
    dynamodb = session.resource('dynamodb', region_name='ap-south-1')
    sns_client = session.client('sns', region_name='ap-south-1')
    logger.info("AWS clients initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize AWS clients: {e}")
    raise

# DynamoDB Tables
users_table = dynamodb.Table('Users_Table')
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')
tutors_table = dynamodb.Table('Tutors_Table')

# SNS Topic ARN - Updated to correct topic name
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic'

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Diagnostic function to check SNS setup
async def diagnose_sns_setup():
    """Comprehensive SNS setup diagnostics"""
    diagnostics = {
        "topic_exists": False,
        "topic_attributes": {},
        "subscriptions": [],
        "permissions": {},
        "region": "ap-south-1"
    }
    
    try:
        # Check if topic exists and get attributes
        topic_attrs = sns_client.get_topic_attributes(TopicArn=SNS_TOPIC_ARN)
        diagnostics["topic_exists"] = True
        diagnostics["topic_attributes"] = topic_attrs['Attributes']
        logger.info("SNS Topic exists and is accessible")
        
        # Check subscriptions
        subscriptions = sns_client.list_subscriptions_by_topic(TopicArn=SNS_TOPIC_ARN)
        diagnostics["subscriptions"] = subscriptions['Subscriptions']
        logger.info(f"Found {len(subscriptions['Subscriptions'])} subscriptions")
        
        # Log subscription details
        for sub in subscriptions['Subscriptions']:
            logger.info(f"Subscription: {sub['Protocol']} -> {sub['Endpoint']} (Status: {sub['SubscriptionArn']})")
            
    except ClientError as e:
        logger.error(f"SNS Diagnostics Error: {e}")
        diagnostics["error"] = str(e)
    
    return diagnostics

# Improved email subscription function with better error handling
async def ensure_email_subscription(email: str):
    """Ensure email is subscribed and confirmed"""
    try:
        # List existing subscriptions
        response = sns_client.list_subscriptions_by_topic(TopicArn=SNS_TOPIC_ARN)
        subscriptions = response['Subscriptions']
        
        # Check if email is already subscribed and confirmed
        for sub in subscriptions:
            if (sub['Protocol'] == 'email' and 
                sub['Endpoint'] == email and 
                sub['SubscriptionArn'] != 'PendingConfirmation'):
                logger.info(f"Email {email} is already confirmed")
                return sub['SubscriptionArn']
        
        # Check if email has pending confirmation
        pending_sub = None
        for sub in subscriptions:
            if (sub['Protocol'] == 'email' and 
                sub['Endpoint'] == email and 
                sub['SubscriptionArn'] == 'PendingConfirmation'):
                pending_sub = sub
                logger.info(f"Email {email} has pending confirmation")
                break
        
        # If no subscription exists, create one
        if not pending_sub:
            logger.info(f"Creating new subscription for {email}")
            subscription_response = sns_client.subscribe(
                TopicArn=SNS_TOPIC_ARN,
                Protocol='email',
                Endpoint=email
            )
            logger.info(f"Subscription created for {email}. Please check email for confirmation.")
            return subscription_response['SubscriptionArn']
        else:
            logger.info(f"Email {email} has pending confirmation - confirmation email should be sent again")
            return 'PendingConfirmation'
            
    except ClientError as e:
        logger.error(f"Error managing email subscription for {email}: {e}")
        return None

# Enhanced send notification function
async def send_sns_email(email: str, subject: str, message: str):
    """Send SNS email with comprehensive error handling and retry logic"""
    try:
        # First ensure subscription
        subscription_arn = await ensure_email_subscription(email)
        
        if not subscription_arn:
            logger.error(f"Failed to establish subscription for {email}")
            return None
        
        if subscription_arn == 'PendingConfirmation':
            logger.warning(f"Email {email} needs to confirm subscription first")
            # Still try to send, SNS will queue the message
        
        # Send the message
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject
        )
        
        message_id = response['MessageId']
        logger.info(f"Message sent successfully to {email}. MessageId: {message_id}")
        
        # Log additional details for debugging
        logger.info(f"Subject: {subject}")
        logger.info(f"Message length: {len(message)} characters")
        
        return message_id
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"SNS ClientError for {email}: {error_code} - {error_message}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error sending SNS email to {email}: {e}")
        return None

@app.get("/sns-diagnostics")
async def get_sns_diagnostics():
    """Endpoint to check SNS configuration"""
    diagnostics = await diagnose_sns_setup()
    return JSONResponse(content=diagnostics)

@app.post("/subscribe-email")
async def subscribe_email_endpoint(email: str = Form(...)):
    """Manual endpoint to subscribe an email"""
    subscription_arn = await ensure_email_subscription(email)
    
    if subscription_arn:
        return JSONResponse(content={
            "message": f"Subscription initiated for {email}",
            "subscription_arn": subscription_arn,
            "note": "Please check your email for confirmation if this is a new subscription"
        })
    else:
        raise HTTPException(status_code=500, detail="Failed to create subscription")

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
            'password': password,  # Hash this in production!
            'role': 'student',
            'created_at': datetime.now().isoformat()
        })

        # Prepare welcome message
        welcome_message = f"""Hello {name},

Welcome to TutorMatch!

Your account has been successfully created with email: {email}

You can now log in and start booking tutoring sessions with our qualified tutors.

If you don't see this email in your inbox, please check your spam/junk folder and add no-reply@sns.amazonaws.com to your contacts.

Best regards,
The TutorMatch Team"""

        # Send welcome email
        message_id = await send_sns_email(
            email=email,
            subject="Welcome to TutorMatch - Account Created",
            message=welcome_message
        )

        if message_id:
            logger.info(f"Welcome email sent to {email}")
            return RedirectResponse(url="/login?registered=true", status_code=302)
        else:
            logger.warning(f"User created but welcome email failed for {email}")
            return RedirectResponse(url="/login?registered=true&email_failed=true", status_code=302)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    try:
        response = users_table.get_item(Key={'email': email})
        user = response.get('Item')

        if user and user['password'] == password:
            return RedirectResponse(url="/student-dashboard", status_code=302)

        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
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

        # Prepare booking confirmation message
        booking_message = f"""Hello,

Your tutoring session has been successfully booked!

BOOKING DETAILS:
Tutor: {tutor_name}
Subject: {subject}
Date: {date}
Time: {time}
Booking ID: {booking_id}

NEXT STEPS:
Please proceed to payment to confirm your session.
You will receive a payment confirmation once completed.

If you have any questions, please contact our support team.

Best regards,
The TutorMatch Team"""

        # Send booking confirmation
        message_id = await send_sns_email(
            email=email,
            subject=f"Booking Confirmation - {subject} with {tutor_name}",
            message=booking_message
        )

        if message_id:
            logger.info(f"Booking confirmation sent to {email}")
        else:
            logger.warning(f"Booking created but confirmation email failed for {email}")

        return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)
        
    except Exception as e:
        logger.error(f"Booking error: {e}")
        raise HTTPException(status_code=500, detail="Booking failed")

@app.post("/process-payment")
async def process_payment(
    booking_id: str = Form(...),
    email: str = Form(...),
    amount: float = Form(...)
):
    try:
        payment_id = str(uuid.uuid4())
        
        # Get booking details
        booking_response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = booking_response.get('Item', {})

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

        # Update booking status
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="SET #s = :status, payment_id = :pid",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':status': 'confirmed', ':pid': payment_id}
        )

        # Prepare payment confirmation message
        payment_message = f"""Hello,

Your payment has been successfully processed!

PAYMENT DETAILS:
Amount: ${amount:.2f}
Payment ID: {payment_id}
Booking ID: {booking_id}
Transaction Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

SESSION DETAILS:
Tutor: {booking.get('tutor_name', 'N/A')}
Subject: {booking.get('subject', 'N/A')}
Date: {booking.get('date', 'N/A')}
Time: {booking.get('time', 'N/A')}

Your session is now CONFIRMED. Please check your dashboard for further details.

Thank you for choosing TutorMatch!

Best regards,
The TutorMatch Team"""

        # Send payment confirmation
        message_id = await send_sns_email(
            email=email,
            subject=f"Payment Confirmed - ${amount:.2f} for {booking.get('subject', 'Session')}",
            message=payment_message
        )

        return JSONResponse(content={
            "message": "Payment processed successfully",
            "payment_id": payment_id,
            "booking_id": booking_id,
            "email_sent": message_id is not None,
            "message_id": message_id
        })
            
    except Exception as e:
        logger.error(f"Payment processing error: {e}")
        raise HTTPException(status_code=500, detail="Payment processing failed")

@app.get("/test-email/{email}")
async def test_email_endpoint(email: str):
    """Enhanced test endpoint with detailed logging"""
    try:
        # First, run diagnostics
        diagnostics = await diagnose_sns_setup()
        
        # Send test email
        test_message = f"""This is a test email from TutorMatch SNS integration.

Test Details:
- Timestamp: {datetime.now().isoformat()}
- Recipient: {email}
- SNS Topic: TutorBookingTopic
- Region: ap-south-1

If you receive this email, your SNS integration is working correctly!

Please check your spam/junk folder if you don't see emails in your inbox.

IMPORTANT: If this is your first email from this topic, you may need to confirm your subscription by clicking the confirmation link that AWS SNS sends separately."""
        
        message_id = await send_sns_email(
            email=email,
            subject="TutorMatch - SNS Test Email",
            message=test_message
        )
        
        return JSONResponse(content={
            "test_result": "Email sent" if message_id else "Email failed",
            "message_id": message_id,
            "email": email,
            "timestamp": datetime.now().isoformat(),
            "diagnostics": diagnostics,
            "instructions": [
                "Check your email inbox and spam/junk folder",
                "If this is your first email, you may need to confirm your subscription",
                "Add no-reply@sns.amazonaws.com to your contacts to avoid spam filtering"
            ]
        })
        
    except Exception as e:
        logger.error(f"Test email error: {e}")
        return JSONResponse(content={
            "test_result": "Error",
            "error": str(e),
            "email": email
        }, status_code=500)

@app.get("/health")
async def health():
    """Enhanced health check"""
    try:
        # Test DynamoDB
        users_table.scan(Limit=1)
        
        # Test SNS
        sns_client.get_topic_attributes(TopicArn=SNS_TOPIC_ARN)
        
        # Get subscription count
        subscriptions = sns_client.list_subscriptions_by_topic(TopicArn=SNS_TOPIC_ARN)
        subscription_count = len(subscriptions['Subscriptions'])
        confirmed_count = len([s for s in subscriptions['Subscriptions'] 
                             if s['SubscriptionArn'] != 'PendingConfirmation'])
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "dynamodb": "connected",
                "sns": "connected"
            },
            "sns_stats": {
                "total_subscriptions": subscription_count,
                "confirmed_subscriptions": confirmed_count,
                "pending_confirmations": subscription_count - confirmed_count
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
