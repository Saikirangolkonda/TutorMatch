from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import uuid
import os
import boto3
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
    bookings_table = dynamodb.Table('Bookings_Table')
    payments_table = dynamodb.Table('Payments_Table')
    tutors_table = dynamodb.Table('Tutors_Table')
    users_table = dynamodb.Table('Users_Table')
    
    logger.info("AWS services initialized successfully")
except Exception as e:
    logger.error(f"Error initializing AWS services: {e}")
    # Fallback to local storage for development
    dynamodb = None
    sns_client = None

# Initialize tutors_data with error handling
tutors_data = {}
try:
    tutors_file_path = os.path.join("templates", "tutors_data.json")
    if os.path.exists(tutors_file_path):
        with open(tutors_file_path) as f:
            tutors_data = json.load(f)
    else:
        # Create default tutors data if file doesn't exist
        tutors_data = {
            "tutor1": {
                "name": "John Smith",
                "subjects": ["Mathematics", "Physics"],
                "rate": 30,
                "rating": 4.8,
                "bio": "Experienced math and physics tutor with 5+ years of teaching experience.",
                "availability": ["Monday 9-17", "Wednesday 9-17", "Friday 9-17"]
            },
            "tutor2": {
                "name": "Sarah Johnson",
                "subjects": ["English", "Literature"],
                "rate": 25,
                "rating": 4.6,
                "bio": "English literature specialist, helping students excel in writing and analysis.",
                "availability": ["Tuesday 10-18", "Thursday 10-18", "Saturday 9-15"]
            }
        }
        # Save default data to file and DynamoDB
        os.makedirs("templates", exist_ok=True)
        with open(tutors_file_path, 'w') as f:
            json.dump(tutors_data, f, indent=2)
        
        # Initialize DynamoDB with default tutors
        if tutors_table:
            try:
                for tutor_id, tutor_data in tutors_data.items():
                    tutor_item = {
                        'tutor_id': tutor_id,
                        **tutor_data,
                        'created_at': datetime.now().isoformat()
                    }
                    tutors_table.put_item(Item=tutor_item)
                logger.info("Default tutors added to DynamoDB")
            except Exception as e:
                logger.error(f"Error adding default tutors to DynamoDB: {e}")
                
except Exception as e:
    logger.error(f"Error loading tutors data: {e}")
    tutors_data = {}

# Mock database fallback (for development)
users = {}
sessions = {}
session_requests = {}
bookings = {}
payments = {}

# Initialize templates and static files with error handling
try:
    templates = Jinja2Templates(directory="templates")
    # Only mount static files if directory exists
    if os.path.exists("static"):
        app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logger.error(f"Error setting up templates/static files: {e}")

# DynamoDB helper functions
async def get_user_from_db(email: str) -> Optional[Dict[str, Any]]:
    """Get user from DynamoDB"""
    if not users_table:
        return users.get(email)
    
    try:
        response = users_table.get_item(Key={'email': email})
        return response.get('Item')
    except ClientError as e:
        logger.error(f"Error getting user from DynamoDB: {e}")
        return None

async def save_user_to_db(user_data: Dict[str, Any]) -> bool:
    """Save user to DynamoDB"""
    if not users_table:
        users[user_data['email']] = user_data
        return True
    
    try:
        user_data['created_at'] = datetime.now().isoformat()
        users_table.put_item(Item=user_data)
        return True
    except ClientError as e:
        logger.error(f"Error saving user to DynamoDB: {e}")
        return False

async def save_booking_to_db(booking_data: Dict[str, Any]) -> bool:
    """Save booking to DynamoDB"""
    if not bookings_table:
        bookings[booking_data['booking_id']] = booking_data
        return True
    
    try:
        bookings_table.put_item(Item=booking_data)
        return True
    except ClientError as e:
        logger.error(f"Error saving booking to DynamoDB: {e}")
        return False

async def get_booking_from_db(booking_id: str) -> Optional[Dict[str, Any]]:
    """Get booking from DynamoDB"""
    if not bookings_table:
        return bookings.get(booking_id)
    
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        return response.get('Item')
    except ClientError as e:
        logger.error(f"Error getting booking from DynamoDB: {e}")
        return None

async def save_payment_to_db(payment_data: Dict[str, Any]) -> bool:
    """Save payment to DynamoDB"""
    if not payments_table:
        payments[payment_data['payment_id']] = payment_data
        return True
    
    try:
        payments_table.put_item(Item=payment_data)
        return True
    except ClientError as e:
        logger.error(f"Error saving payment to DynamoDB: {e}")
        return False

async def get_student_bookings_from_db(student_email: str = None) -> list:
    """Get all bookings for a student from DynamoDB"""
    if not bookings_table:
        return [{"id": k, **v} for k, v in bookings.items()]
    
    try:
        response = bookings_table.scan()
        items = response.get('Items', [])
        
        # Filter by student email if provided
        if student_email:
            items = [item for item in items if item.get('student_email') == student_email]
        
        return items
    except ClientError as e:
        logger.error(f"Error getting bookings from DynamoDB: {e}")
        return []

async def send_sns_notification(message: str, subject: str = "TutorMatch Notification"):
    """Send notification via SNS"""
    if not sns_client:
        logger.info(f"SNS not available. Would send: {subject} - {message}")
        return
    
    try:
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject
        )
        logger.info(f"SNS notification sent: {response['MessageId']}")
    except ClientError as e:
        logger.error(f"Error sending SNS notification: {e}")

# Homepage route
@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    try:
        return templates.TemplateResponse("homepage.html", {"request": request})
    except Exception:
        # Fallback if template doesn't exist
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
    """Redirect Get Started button to register page"""
    return RedirectResponse(url="/register", status_code=302)

@app.get("/browse-tutors")
async def browse_tutors():
    """Redirect Browse Tutors button to login page"""
    return RedirectResponse(url="/login", status_code=302)

@app.get("/join-as-student")
async def join_as_student():
    """Redirect Join as Student button to register page"""
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
    user = await get_user_from_db(email)
    if user and user.get("password") == password:
        return RedirectResponse(url="/student-dashboard", status_code=302)
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/register")
async def register(
    email: str = Form(...), 
    password: str = Form(...), 
    name: str = Form(...)
):
    existing_user = await get_user_from_db(email)
    if not existing_user:
        user_data = {
            "email": email,
            "password": password,
            "name": name,
            "role": "student"
        }
        success = await save_user_to_db(user_data)
        if success:
            # Send welcome notification
            await send_sns_notification(
                f"Welcome to TutorMatch, {name}! Your account has been created successfully.",
                "Welcome to TutorMatch"
            )
            return RedirectResponse(url="/login", status_code=302)
        else:
            raise HTTPException(status_code=500, detail="Failed to create user")
    raise HTTPException(status_code=400, detail="User already exists")

# Dashboard and main application routes
@app.get("/student-dashboard", response_class=HTMLResponse)
async def student_dashboard(request: Request):
    try:
        return templates.TemplateResponse("student_dashboard.html", {
            "request": request
        })
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
        return templates.TemplateResponse("tutor_search.html", {
            "request": request,
            "tutors_with_id": [{"id": k, **v} for k, v in tutors_data.items()]
        })
    except Exception:
        # Fallback HTML with tutor list
        tutors_html = ""
        for tutor_id, tutor in tutors_data.items():
            tutors_html += f"""
            <div style="border: 1px solid #ccc; padding: 10px; margin: 10px 0;">
                <h3>{tutor['name']}</h3>
                <p>Subjects: {', '.join(tutor.get('subjects', []))}</p>
                <p>Rate: ${tutor.get('rate', 25)}/hour</p>
                <p>Rating: {tutor.get('rating', 4.5)}/5</p>
                <p>{tutor.get('bio', 'No bio available')}</p>
                <a href="/tutor-profile/{tutor_id}">View Profile</a>
            </div>
            """
        
        return HTMLResponse(f"""
        <html>
            <head><title>Find Tutors - TutorMatch</title></head>
            <body>
                <h1>Find Tutors</h1>
                <div>{tutors_html}</div>
                <p><a href="/student-dashboard">Back to Dashboard</a></p>
            </body>
        </html>
        """)

# Tutor profile and booking routes
@app.get("/tutor-profile/{tutor_id}", response_class=HTMLResponse)
async def tutor_profile(request: Request, tutor_id: str):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")
    
    try:
        return templates.TemplateResponse("tutor_profile.html", {
            "request": request,
            "tutor": tutor,
            "tutor_id": tutor_id
        })
    except Exception:
        return HTMLResponse(f"""
        <html>
            <head><title>{tutor['name']} - TutorMatch</title></head>
            <body>
                <h1>{tutor['name']}</h1>
                <p><strong>Subjects:</strong> {', '.join(tutor.get('subjects', []))}</p>
                <p><strong>Rate:</strong> ${tutor.get('rate', 25)}/hour</p>
                <p><strong>Rating:</strong> {tutor.get('rating', 4.5)}/5</p>
                <p><strong>Bio:</strong> {tutor.get('bio', 'No bio available')}</p>
                <p><strong>Availability:</strong> {', '.join(tutor.get('availability', ['Contact for availability']))}</p>
                
                <h2>Book a Session</h2>
                <form method="post" action="/book-session/{tutor_id}">
                    <p>
                        <label>Date:</label><br>
                        <input type="date" name="date" required>
                    </p>
                    <p>
                        <label>Time:</label><br>
                        <input type="time" name="time" required>
                    </p>
                    <p>
                        <label>Subject:</label><br>
                        <select name="subject" required>
                            {''.join([f'<option value="{subject}">{subject}</option>' for subject in tutor.get('subjects', ['General'])])}
                        </select>
                    </p>
                    <p>
                        <label>Session Type:</label><br>
                        <select name="session_type">
                            <option value="Single Session">Single Session</option>
                            <option value="Weekly">Weekly</option>
                            <option value="Monthly">Monthly</option>
                        </select>
                    </p>
                    <p>
                        <label>Number of Sessions:</label><br>
                        <input type="number" name="sessions_count" value="1" min="1">
                    </p>
                    <p>
                        <label>Learning Goals:</label><br>
                        <textarea name="learning_goals" rows="3"></textarea>
                    </p>
                    <p>
                        <label>Session Format:</label><br>
                        <select name="session_format">
                            <option value="Online Video Call">Online Video Call</option>
                            <option value="In Person">In Person</option>
                        </select>
                    </p>
                    <input type="hidden" name="total_price" value="{tutor.get('rate', 25)}">
                    <button type="submit">Book Session</button>
                </form>
                
                <p><a href="/tutor-search">Back to Search</a></p>
            </body>
        </html>
        """)

@app.get("/book-session/{tutor_id}", response_class=HTMLResponse)
async def book_session_page(request: Request, tutor_id: str):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")

    try:
        return templates.TemplateResponse("booksession.html", {
            "request": request,
            "tutor": tutor,
            "tutor_id": tutor_id
        })
    except Exception:
        # Redirect to tutor profile for booking
        return RedirectResponse(url=f"/tutor-profile/{tutor_id}", status_code=302)

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
    session_format: str = Form("Online Video Call"),
    student_email: str = Form("")  # This should come from session in production
):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")

    booking_id = str(uuid.uuid4())
    
    # Calculate total price based on sessions count
    calculated_price = tutor.get('rate', 25) * sessions_count

    booking = {
        "booking_id": booking_id,
        "tutor_id": tutor_id,
        "tutor_data": tutor,
        "student_email": student_email,
        "date": date,
        "time": time,
        "subject": subject,
        "session_type": session_type,
        "sessions_count": sessions_count,
        "total_price": calculated_price,
        "learning_goals": learning_goals,
        "session_format": session_format,
        "status": "pending_payment",
        "created_at": datetime.now().isoformat()
    }

    success = await save_booking_to_db(booking)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save booking")

    # Send booking notification
    await send_sns_notification(
        f"New booking created: {tutor['name']} - {subject} on {date} at {time}. Booking ID: {booking_id}",
        "New Tutor Booking"
    )

    return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)

# Payment processing routes
@app.get("/payment", response_class=HTMLResponse)
async def payment_page(request: Request, booking_id: str = ""):
    if not booking_id:
        raise HTTPException(status_code=404, detail="Booking ID required")
    
    booking = await get_booking_from_db(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    try:
        return templates.TemplateResponse("payment.html", {
            "request": request,
            "booking": booking,
            "booking_id": booking_id
        })
    except Exception:
        return HTMLResponse(f"""
        <html>
            <head><title>Payment - TutorMatch</title></head>
            <body>
                <h1>Payment</h1>
                <h2>Booking Summary</h2>
                <p><strong>Tutor:</strong> {booking['tutor_data']['name']}</p>
                <p><strong>Subject:</strong> {booking['subject']}</p>
                <p><strong>Date:</strong> {booking['date']}</p>
                <p><strong>Time:</strong> {booking['time']}</p>
                <p><strong>Sessions:</strong> {booking['sessions_count']}</p>
                <p><strong>Total:</strong> ${booking['total_price']}</p>
                
                <h2>Payment Details</h2>
                <form method="post" action="/process-payment">
                    <input type="hidden" name="booking_id" value="{booking_id}">
                    <p>
                        <label>Payment Method:</label><br>
                        <select name="payment_method" required>
                            <option value="credit_card">Credit Card</option>
                            <option value="debit_card">Debit Card</option>
                            <option value="paypal">PayPal</option>
                        </select>
                    </p>
                    <p>
                        <label>Card Number:</label><br>
                        <input type="text" name="card_number" placeholder="1234 5678 9012 3456">
                    </p>
                    <p>
                        <label>Cardholder Name:</label><br>
                        <input type="text" name="cardholder_name">
                    </p>
                    <p>
                        <label>Email:</label><br>
                        <input type="email" name="email" required>
                    </p>
                    <p>
                        <label>Phone:</label><br>
                        <input type="tel" name="phone" required>
                    </p>
                    <button type="submit">Process Payment</button>
                </form>
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
    booking = await get_booking_from_db(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Process payment (mock)
    payment_id = str(uuid.uuid4())
    payment_data = {
        "payment_id": payment_id,
        "booking_id": booking_id,
        "amount": booking["total_price"],
        "payment_method": payment_method,
        "status": "completed",
        "cardholder_name": cardholder_name,
        "email": email,
        "phone": phone,
        "created_at": datetime.now().isoformat()
    }
    
    success = await save_payment_to_db(payment_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to process payment")
    
    # Update booking status
    booking["status"] = "confirmed"
    booking["payment_id"] = payment_id
    await save_booking_to_db(booking)
    
    # Send payment confirmation notification
    await send_sns_notification(
        f"Payment confirmed for booking {booking_id}. Amount: ${booking['total_price']}. Session with {booking['tutor_data']['name']} on {booking['date']}.",
        "Payment Confirmation - TutorMatch"
    )
    
    return RedirectResponse(url=f"/confirmation?booking_id={booking_id}", status_code=302)

@app.get("/confirmation", response_class=HTMLResponse)
async def confirmation_page(request: Request, booking_id: str = ""):
    if not booking_id:
        raise HTTPException(status_code=404, detail="Booking ID required")
    
    booking = await get_booking_from_db(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    try:
        return templates.TemplateResponse("confirmation.html", {
            "request": request,
            "booking": booking
        })
    except Exception:
        return HTMLResponse(f"""
        <html>
            <head><title>Booking Confirmed - TutorMatch</title></head>
            <body>
                <h1>Booking Confirmed!</h1>
                <p>Your session has been successfully booked.</p>
                
                <h2>Booking Details</h2>
                <p><strong>Booking ID:</strong> {booking['booking_id']}</p>
                <p><strong>Tutor:</strong> {booking['tutor_data']['name']}</p>
                <p><strong>Subject:</strong> {booking['subject']}</p>
                <p><strong>Date:</strong> {booking['date']}</p>
                <p><strong>Time:</strong> {booking['time']}</p>
                <p><strong>Format:</strong> {booking['session_format']}</p>
                <p><strong>Total Paid:</strong> ${booking['total_price']}</p>
                
                <p><a href="/student-dashboard">Back to Dashboard</a></p>
            </body>
        </html>
        """)

# API endpoints
@app.get("/api/student-data")
async def get_student_data(student_email: str = ""):
    """Get student's bookings, payments, and notifications"""
    
    student_bookings = await get_student_bookings_from_db(student_email)
    student_payments = []
    notifications = []
    
    # Format bookings data
    formatted_bookings = []
    for booking in student_bookings:
        formatted_booking = {
            "id": booking.get("booking_id", booking.get("id")),
            "tutor_name": booking.get("tutor_data", {}).get("name", "Unknown"),
            "subject": booking.get("subject"),
            "date": booking.get("date"),
            "time": booking.get("time"),
            "status": booking.get("status"),
            "total_price": booking.get("total_price"),
            "session_format": booking.get("session_format"),
            "created_at": booking.get("created_at")
        }
        formatted_bookings.append(formatted_booking)
        
        # Get payment info if available
        payment_id = booking.get("payment_id")
        if payment_id:
            # In a real implementation, you'd query the payments table
            student_payments.append({
                "id": payment_id,
                "tutor_name": booking.get("tutor_data", {}).get("name", "Unknown"),
                "amount": booking.get("total_price"),
                "status": "completed",
                "date": booking.get("created_at"),
                "method": "credit_card"
            })
        
        # Generate notifications
        try:
            booking_date = datetime.fromisoformat(booking.get("created_at", datetime.now().isoformat()))
            
            if booking.get("status") == "confirmed":
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your {booking.get('subject')} session with {booking.get('tutor_data', {}).get('name', 'Unknown')} is confirmed for {booking.get('date')}.",
                    "date": booking_date.strftime("%B %d, %Y")
                })
                
                try:
                    session_datetime = datetime.strptime(f"{booking.get('date')} {booking.get('time')}", "%Y-%m-%d %H:%M")
                    if session_datetime > datetime.now() and session_datetime < datetime.now() + timedelta(days=1):
                        notifications.append({
                            "type": "reminder",
                            "title": "Session Reminder",
                            "message": f"You have a {booking.get('subject')} session tomorrow at {booking.get('time')}.",
                            "date": datetime.now().strftime("%B %d, %Y")
                        })
                except (ValueError, TypeError):
                    pass  # Invalid date/time format
        except (ValueError, TypeError):
            pass  # Invalid datetime format
    
    formatted_bookings.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    student_payments.sort(key=lambda x: x.get("date", ""), reverse=True)
    notifications.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    return {
        "bookings": formatted_bookings,
        "payments": student_payments,
        "notifications": notifications
    }

# Utility routes
@app.get("/logout")
async def logout():
    return RedirectResponse(url="/", status_code=302)

# Health check endpoint
@app.get("/health")
async def health_check():
    health_status = {
        "status": "healthy",
        "tutors_count": len(tutors_data),
        "aws_services": {
            "dynamodb": dynamodb is not None,
            "sns": sns_client is not None
        },
        "timestamp": datetime.now().isoformat()
    }
    
    # Test DynamoDB connection
    if dynamodb:
        try:
            # Test each table
            bookings_table.table_status
            payments_table.table_status
            tutors_table.table_status
            users_table.table_status
            health_status["dynamodb_tables"] = "accessible"
        except Exception as e:
            health_status["dynamodb_tables"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
    
    # Test SNS connection
    if sns_client:
        try:
            sns_client.get_topic_attributes(TopicArn=SNS_TOPIC_ARN)
            health_status["sns_topic"] = "accessible"
        except Exception as e:
            health_status["sns_topic"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
    
    return health_status

# Admin endpoints for managing data
@app.get("/admin/sync-tutors")
async def sync_tutors_to_db():
    """Sync local tutors data to DynamoDB"""
    if not tutors_table:
        return {"error": "DynamoDB not available"}
    
    synced_count = 0
    errors = []
    
    for tutor_id, tutor_data in tutors_data.items():
        try:
            tutor_item = {
                'tutor_id': tutor_id,
                **tutor_data,
                'updated_at': datetime.now().isoformat()
            }
            tutors_table.put_item(Item=tutor_item)
            synced_count += 1
        except Exception as e:
            errors.append(f"Error syncing {tutor_id}: {str(e)}")
    
    return {
        "synced_count": synced_count,
        "total_tutors": len(tutors_data),
        "errors": errors
    }

@app.get("/admin/stats")
async def get_admin_stats():
    """Get admin statistics"""
    stats = {
        "local_data": {
            "tutors": len(tutors_data),
            "users": len(users),
            "bookings": len(bookings),
            "payments": len(payments)
        }
    }
    
    # Get DynamoDB stats if available
    if dynamodb:
        try:
            # Get table item counts (approximate)
            tables_info = {}
            for table_name, table in [
                ("bookings", bookings_table),
                ("payments", payments_table),
                ("tutors", tutors_table),
                ("users", users_table)
            ]:
                try:
                    response = table.describe_table()
                    tables_info[table_name] = {
                        "status": response['Table']['TableStatus'],
                        "item_count": response['Table'].get('ItemCount', 0)
                    }
                except Exception as e:
                    tables_info[table_name] = {"error": str(e)}
            
            stats["dynamodb_tables"] = tables_info
        except Exception as e:
            stats["dynamodb_error"] = str(e)
    
    return stats

# Additional utility functions
async def cleanup_expired_sessions():
    """Clean up expired booking sessions (can be called by a scheduled job)"""
    if not bookings_table:
        return {"message": "DynamoDB not available"}
    
    try:
        # Get all pending bookings older than 1 hour
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(hours=1)
        
        response = bookings_table.scan(
            FilterExpression="attribute_exists(created_at) AND #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "pending_payment"}
        )
        
        expired_count = 0
        for item in response.get('Items', []):
            try:
                created_at = datetime.fromisoformat(item['created_at'])
                if created_at < cutoff_time:
                    # Update status to expired
                    bookings_table.update_item(
                        Key={'booking_id': item['booking_id']},
                        UpdateExpression="SET #status = :expired_status",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={":expired_status": "expired"}
                    )
                    expired_count += 1
            except (ValueError, KeyError):
                continue
        
        return {"expired_bookings": expired_count}
    except Exception as e:
        logger.error(f"Error cleaning up expired sessions: {e}")
        return {"error": str(e)}

@app.get("/admin/cleanup-expired")
async def cleanup_expired_bookings():
    """Admin endpoint to clean up expired bookings"""
    return await cleanup_expired_sessions()

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return HTMLResponse(
        content="""
        <html>
            <head><title>Page Not Found - TutorMatch</title></head>
            <body>
                <h1>Page Not Found</h1>
                <p>The page you're looking for doesn't exist.</p>
                <p><a href="/">Go back to homepage</a></p>
            </body>
        </html>
        """,
        status_code=404
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: HTTPException):
    return HTMLResponse(
        content="""
        <html>
            <head><title>Server Error - TutorMatch</title></head>
            <body>
                <h1>Server Error</h1>
                <p>Something went wrong. Please try again later.</p>
                <p><a href="/">Go back to homepage</a></p>
            </body>
        </html>
        """,
        status_code=500
    )

# Startup event
@app.on_event("startup")
async def startup_event():
    logger.info("TutorMatch application starting up...")
    logger.info(f"AWS Region: {AWS_REGION}")
    logger.info(f"SNS Topic ARN: {SNS_TOPIC_ARN}")
    logger.info(f"DynamoDB available: {dynamodb is not None}")
    logger.info(f"SNS available: {sns_client is not None}")
    
    # Send startup notification
    await send_sns_notification(
        "TutorMatch application has started successfully on EC2.",
        "TutorMatch Startup Notification"
    )

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("TutorMatch application shutting down...")
    
    # Send shutdown notification
    await send_sns_notification(
        "TutorMatch application is shutting down.",
        "TutorMatch Shutdown Notification"
    )

if __name__ == "__main__":
    # Configuration for production deployment
    port = int(os.getenv('PORT', 8000))
    host = os.getenv('HOST', '0.0.0.0')
    
    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(
        app, 
        host=host, 
        port=port,
        log_level="info",
        access_log=True
    )
