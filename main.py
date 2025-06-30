import boto3
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import uuid
import os
from decimal import Decimal
from botocore.exceptions import ClientError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TutorMatch", description="Connect students with tutors")

# AWS Configuration
AWS_REGION = os.getenv('AWS_REGION', 'ap-south-1')
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN', 'arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic')

# Initialize AWS clients
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    sns_client = boto3.client('sns', region_name=AWS_REGION)
    
    # DynamoDB tables
    users_table = dynamodb.Table('Users_Table')
    tutors_table = dynamodb.Table('Tutors_Table')
    bookings_table = dynamodb.Table('Bookings_Table')
    payments_table = dynamodb.Table('Payments_Table')
    
    logger.info("AWS services initialized successfully")
except Exception as e:
    logger.error(f"Error initializing AWS services: {e}")
    raise

# Helper functions for DynamoDB operations
def decimal_to_float(obj):
    """Convert Decimal objects to float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(v) for v in obj]
    return obj

def float_to_decimal(obj):
    """Convert float objects to Decimal for DynamoDB"""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [float_to_decimal(v) for v in obj]
    return obj

# Initialize tutors data in DynamoDB
async def initialize_tutors_data():
    """Initialize default tutors data if not exists"""
    try:
        # Check if tutors exist
        response = tutors_table.scan(Limit=1)
        if response['Count'] == 0:
            # Create default tutors
            default_tutors = [
                {
                    "tutor_id": "tutor1",
                    "name": "John Smith",
                    "subjects": ["Mathematics", "Physics"],
                    "rate": Decimal("30"),
                    "rating": Decimal("4.8"),
                    "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
                    "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"],
                    "created_at": datetime.now().isoformat()
                },
                {
                    "tutor_id": "tutor2",
                    "name": "Sarah Johnson",
                    "subjects": ["English", "Literature"],
                    "rate": Decimal("25"),
                    "rating": Decimal("4.6"),
                    "bio": "English literature specialist, helping students excel in writing and analysis.",
                    "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"],
                    "created_at": datetime.now().isoformat()
                }
            ]
            
            for tutor in default_tutors:
                tutors_table.put_item(Item=tutor)
            
            logger.info("Default tutors data initialized")
    except Exception as e:
        logger.error(f"Error initializing tutors data: {e}")

# SNS notification function
async def send_notification(email: str, subject: str, message: str):
    """Send email notification via SNS"""
    try:
        # Create message with both session and payment info
        sns_message = {
            "default": message,
            "email": message
        }
        
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(sns_message),
            Subject=subject,
            MessageStructure='json'
        )
        
        logger.info(f"Notification sent successfully: {response['MessageId']}")
        return True
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        return False

# Initialize templates and static files
try:
    templates = Jinja2Templates(directory="templates")
    if os.path.exists("static"):
        app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logger.error(f"Error setting up templates/static files: {e}")

# Startup event
@app.on_event("startup")
async def startup_event():
    await initialize_tutors_data()

# Homepage route
@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    try:
        return templates.TemplateResponse("homepage.html", {"request": request})
    except Exception:
        return HTMLResponse("""
        <html>
            <head><title>TutorMatch</title></head>
            <body>
                <h1>Welcome to TutorMatch</h1>
                <p>Connect with experienced tutors!</p>
                <a href="/login">Login</a> | <a href="/register">Get Started</a> | <a href="/login">Browse Tutors</a> | <a href="/register">Join as Student</a>
            </body>
        </html>
        """)

# Button redirect routes
@app.get("/get-started")
async def get_started():
    return RedirectResponse(url="/register", status_code=302)

@app.get("/browse-tutors")
async def browse_tutors():
    return RedirectResponse(url="/login", status_code=302)

@app.get("/join-as-student")
async def join_as_student():
    return RedirectResponse(url="/register", status_code=302)

# Authentication routes
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    try:
        return templates.TemplateResponse("login.html", {"request": request})
    except Exception:
        return HTMLResponse("""
        <html>
            <head><title>Login - TutorMatch</title></head>
            <body>
                <h1>Student Login</h1>
                <form method="post" action="/login">
                    <p>
                        <label>Email:</label><br>
                        <input type="email" name="email" required>
                    </p>
                    <p>
                        <label>Password:</label><br>
                        <input type="password" name="password" required>
                    </p>
                    <button type="submit">Login</button>
                </form>
                <p><a href="/register">Don't have an account? Register</a></p>
            </body>
        </html>
        """)

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    try:
        return templates.TemplateResponse("register.html", {"request": request})
    except Exception:
        return HTMLResponse("""
        <html>
            <head><title>Register - TutorMatch</title></head>
            <body>
                <h1>Student Registration</h1>
                <form method="post" action="/register">
                    <p>
                        <label>Name:</label><br>
                        <input type="text" name="name" required>
                    </p>
                    <p>
                        <label>Email:</label><br>
                        <input type="email" name="email" required>
                    </p>
                    <p>
                        <label>Password:</label><br>
                        <input type="password" name="password" required>
                    </p>
                    <button type="submit">Register</button>
                </form>
                <p><a href="/login">Already have an account? Login</a></p>
            </body>
        </html>
        """)

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    try:
        response = users_table.get_item(Key={'email': email})
        if 'Item' in response and response['Item']['password'] == password:
            return RedirectResponse(url="/student-dashboard", status_code=302)
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except ClientError as e:
        logger.error(f"DynamoDB error during login: {e}")
        raise HTTPException(status_code=500, detail="Database error")

@app.post("/register")
async def register(
    email: str = Form(...), 
    password: str = Form(...), 
    name: str = Form(...)
):
    try:
        # Check if user already exists
        response = users_table.get_item(Key={'email': email})
        if 'Item' in response:
            raise HTTPException(status_code=400, detail="User already exists")
        
        # Create new user
        user_data = {
            'email': email,
            'password': password,
            'name': name,
            'role': 'student',
            'created_at': datetime.now().isoformat()
        }
        
        users_table.put_item(Item=user_data)
        return RedirectResponse(url="/login", status_code=302)
        
    except ClientError as e:
        logger.error(f"DynamoDB error during registration: {e}")
        raise HTTPException(status_code=500, detail="Database error")

# Dashboard and main application routes
@app.get("/student-dashboard", response_class=HTMLResponse)
async def student_dashboard(request: Request):
    try:
        return templates.TemplateResponse("student_dashboard.html", {"request": request})
    except Exception:
        return HTMLResponse("""
        <html>
            <head><title>Student Dashboard - TutorMatch</title></head>
            <body>
                <h1>Student Dashboard</h1>
                <p>Welcome to your dashboard!</p>
                <ul>
                    <li><a href="/tutor-search">Search for Tutors</a></li>
                    <li><a href="/api/student-data">View My Bookings (JSON)</a></li>
                    <li><a href="/logout">Logout</a></li>
                </ul>
            </body>
        </html>
        """)

@app.get("/tutor-search", response_class=HTMLResponse)
async def tutor_search(request: Request):
    try:
        # Get all tutors from DynamoDB
        response = tutors_table.scan()
        tutors_data = {item['tutor_id']: decimal_to_float(item) for item in response['Items']}
        
        return templates.TemplateResponse("tutor_search.html", {
            "request": request,
            "tutors_with_id": [{"id": k, **v} for k, v in tutors_data.items()]
        })
    except Exception as e:
        logger.error(f"Error fetching tutors: {e}")
        return HTMLResponse("""
        <html>
            <head><title>Find Tutors - TutorMatch</title></head>
            <body>
                <h1>Find Tutors</h1>
                <p>Error loading tutors. Please try again later.</p>
                <p><a href="/student-dashboard">Back to Dashboard</a></p>
            </body>
        </html>
        """)

@app.get("/tutor-profile/{tutor_id}", response_class=HTMLResponse)
async def tutor_profile(request: Request, tutor_id: str):
    try:
        response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="Tutor not found")
        
        tutor = decimal_to_float(response['Item'])
        
        return templates.TemplateResponse("tutor_profile.html", {
            "request": request,
            "tutor": tutor,
            "tutor_id": tutor_id
        })
    except ClientError as e:
        logger.error(f"DynamoDB error fetching tutor: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        return HTMLResponse(f"""
        <html>
            <head><title>Tutor Profile - TutorMatch</title></head>
            <body>
                <h1>Tutor Profile</h1>
                <p>Error loading tutor profile. Please try again later.</p>
                <p><a href="/tutor-search">Back to Search</a></p>
            </body>
        </html>
        """)

@app.post("/book-session/{tutor_id}")
async def book_session_from_profile(
    request: Request,
    tutor_id: str,
    date: str = Form(...),
    time: str = Form(...),
    subject: str = Form(...),
    session_type: str = Form("Single Session"),
    sessions_count: int = Form(1),
    total_price: float = Form(...),
    learning_goals: str = Form(""),
    session_format: str = Form("Online Video Call")
):
    try:
        # Get tutor data
        tutor_response = tutors_table.get_item(Key={'tutor_id': tutor_id})
        if 'Item' not in tutor_response:
            raise HTTPException(status_code=404, detail="Tutor not found")
        
        tutor = decimal_to_float(tutor_response['Item'])
        booking_id = str(uuid.uuid4())
        
        # Calculate total price based on sessions count
        calculated_price = float(tutor.get('rate', 25)) * sessions_count

        booking = {
            "booking_id": booking_id,
            "tutor_id": tutor_id,
            "tutor_data": tutor,
            "date": date,
            "time": time,
            "subject": subject,
            "session_type": session_type,
            "sessions_count": sessions_count,
            "total_price": Decimal(str(calculated_price)),
            "learning_goals": learning_goals,
            "session_format": session_format,
            "status": "pending_payment",
            "created_at": datetime.now().isoformat()
        }

        # Save booking to DynamoDB
        bookings_table.put_item(Item=float_to_decimal(booking))

        return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)
        
    except ClientError as e:
        logger.error(f"DynamoDB error during booking: {e}")
        raise HTTPException(status_code=500, detail="Database error")

@app.get("/payment", response_class=HTMLResponse)
async def payment_page(request: Request, booking_id: str = ""):
    if not booking_id:
        raise HTTPException(status_code=400, detail="Booking ID required")
    
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        booking = decimal_to_float(response['Item'])
        
        return templates.TemplateResponse("payment.html", {
            "request": request,
            "booking": booking,
            "booking_id": booking_id
        })
    except ClientError as e:
        logger.error(f"DynamoDB error fetching booking: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        return HTMLResponse("""
        <html>
            <head><title>Payment - TutorMatch</title></head>
            <body>
                <h1>Payment</h1>
                <p>Error loading payment page. Please try again later.</p>
                <p><a href="/student-dashboard">Back to Dashboard</a></p>
            </body>
        </html>
        """)

@app.post("/process-payment")
async def process_payment(
    booking_id: str = Form(...),
    payment_method: str = Form(...),
    card_number: str = Form(""),
    cardholder_name: str = Form(""),
    email: str = Form(...),
    phone: str = Form(...)
):
    try:
        # Get booking data
        booking_response = bookings_table.get_item(Key={'booking_id': booking_id})
        if 'Item' not in booking_response:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        booking = decimal_to_float(booking_response['Item'])
        
        # Process payment (mock)
        payment_id = str(uuid.uuid4())
        payment_data = {
            "payment_id": payment_id,
            "booking_id": booking_id,
            "amount": Decimal(str(booking["total_price"])),
            "payment_method": payment_method,
            "email": email,
            "phone": phone,
            "status": "completed",
            "created_at": datetime.now().isoformat()
        }
        
        # Save payment to DynamoDB
        payments_table.put_item(Item=payment_data)
        
        # Update booking status
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression='SET #status = :status, payment_id = :payment_id',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'confirmed',
                ':payment_id': payment_id
            }
        )
        
        # Send combined notification
        session_datetime = f"{booking['date']} at {booking['time']}"
        notification_subject = "TutorMatch: Session Confirmed & Payment Processed"
        notification_message = f"""
Dear Student,

Great news! Your tutoring session has been confirmed and payment has been processed successfully.

SESSION DETAILS:
- Tutor: {booking['tutor_data']['name']}
- Subject: {booking['subject']}
- Date & Time: {session_datetime}
- Format: {booking['session_format']}
- Sessions: {booking['sessions_count']}

PAYMENT DETAILS:
- Amount Paid: ${booking['total_price']}
- Payment Method: {payment_method}
- Payment ID: {payment_id}
- Status: Completed

UPCOMING SESSION REMINDER:
Don't forget about your upcoming {booking['subject']} session with {booking['tutor_data']['name']} on {booking['date']} at {booking['time']}.

If you have any questions, please contact us.

Best regards,
TutorMatch Team
        """
        
        # Send notification
        await send_notification(email, notification_subject, notification_message)
        
        return RedirectResponse(url=f"/confirmation?booking_id={booking_id}", status_code=302)
        
    except ClientError as e:
        logger.error(f"DynamoDB error during payment processing: {e}")
        raise HTTPException(status_code=500, detail="Database error")

@app.get("/confirmation", response_class=HTMLResponse)
async def confirmation_page(request: Request, booking_id: str = ""):
    if not booking_id:
        raise HTTPException(status_code=400, detail="Booking ID required")
    
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        booking = decimal_to_float(response['Item'])
        
        return templates.TemplateResponse("confirmation.html", {
            "request": request,
            "booking": booking
        })
    except ClientError as e:
        logger.error(f"DynamoDB error fetching booking: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        return HTMLResponse("""
        <html>
            <head><title>Booking Confirmed - TutorMatch</title></head>
            <body>
                <h1>Booking Confirmed!</h1>
                <p>Your session has been successfully booked and you should receive a confirmation email shortly.</p>
                <p><a href="/student-dashboard">Back to Dashboard</a></p>
            </body>
        </html>
        """)

@app.get("/api/student-data")
async def get_student_data(student_email: str = ""):
    """Get student's bookings, payments, and notifications"""
    try:
        student_bookings = []
        student_payments = []
        notifications = []
        
        # Get all bookings
        bookings_response = bookings_table.scan()
        for booking_item in bookings_response['Items']:
            booking = decimal_to_float(booking_item)
            
            student_bookings.append({
                "id": booking["booking_id"],
                "tutor_name": booking["tutor_data"]["name"],
                "subject": booking["subject"],
                "date": booking["date"],
                "time": booking["time"],
                "status": booking["status"],
                "total_price": booking["total_price"],
                "session_format": booking["session_format"],
                "created_at": booking["created_at"]
            })
            
            # Get payment if exists
            if "payment_id" in booking:
                try:
                    payment_response = payments_table.get_item(Key={'payment_id': booking["payment_id"]})
                    if 'Item' in payment_response:
                        payment = decimal_to_float(payment_response['Item'])
                        student_payments.append({
                            "id": payment["payment_id"],
                            "tutor_name": booking["tutor_data"]["name"],
                            "amount": payment["amount"],
                            "status": payment["status"],
                            "date": payment["created_at"],
                            "method": payment["payment_method"]
                        })
                except ClientError:
                    pass  # Payment not found
            
            # Create notifications
            booking_date = datetime.fromisoformat(booking["created_at"])
            
            if booking["status"] == "confirmed":
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your {booking['subject']} session with {booking['tutor_data']['name']} is confirmed for {booking['date']}.",
                    "date": booking_date.strftime("%B %d, %Y")
                })
                
                try:
                    session_datetime = datetime.strptime(f"{booking['date']} {booking['time']}", "%Y-%m-%d %H:%M")
                    if session_datetime > datetime.now() and session_datetime < datetime.now() + timedelta(days=1):
                        notifications.append({
                            "type": "reminder",
                            "title": "Session Reminder",
                            "message": f"You have a {booking['subject']} session tomorrow at {booking['time']}.",
                            "date": datetime.now().strftime("%B %d, %Y")
                        })
                except ValueError:
                    pass  # Invalid date/time format
        
        # Sort data
        student_bookings.sort(key=lambda x: x["created_at"], reverse=True)
        student_payments.sort(key=lambda x: x["date"], reverse=True)
        notifications.sort(key=lambda x: x["date"], reverse=True)
        
        return {
            "bookings": student_bookings,
            "payments": student_payments,
            "notifications": notifications
        }
        
    except ClientError as e:
        logger.error(f"DynamoDB error fetching student data: {e}")
        raise HTTPException(status_code=500, detail="Database error")

# Utility routes
@app.get("/logout")
async def logout():
    return RedirectResponse(url="/", status_code=302)

# Health check endpoint
@app.get("/health")
async def health_check():
    try:
        # Check DynamoDB connection
        tutors_response = tutors_table.scan(Limit=1)
        tutors_count = tutors_response['Count']
        
        return {
            "status": "healthy",
            "tutors_count": tutors_count,
            "aws_region": AWS_REGION,
            "services": ["dynamodb", "sns"]
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
