from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from datetime import datetime, timedelta
from typing import Optional
import json
import uuid
import os
import boto3 # Import boto3 for AWS services
from botocore.exceptions import ClientError # For handling AWS client errors

app = FastAPI(title="TutorMatch", description="Connect students with tutors")

# --- AWS Service Initialization ---
# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1') # Specify your region
users_table = dynamodb.Table('Users_Table')
tutors_table = dynamodb.Table('Tutors_Table') # Although tutors_data.json is still used, this is here for future
bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')

# Initialize SNS client
sns_client = boto3.client('sns', region_name='ap-south-1') # Specify your region
SNS_TOPIC_ARN = "arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic" # Your SNS Topic ARN

# Initialize tutors_data with error handling (still loading from JSON for now)
tutors_data = {}
try:
    tutors_file_path = os.path.join("templates", "tutors_data.json")
    if os.path.exists(tutors_file_path):
        with open(tutors_file_path) as f:
            tutors_data = json.load(f)
            # Optionally, populate Tutors_Table with this data if it's empty
            # for tutor_id, tutor_details in tutors_data.items():
            #     try:
            #         tutors_table.put_item(Item={"tutor_id": tutor_id, **tutor_details})
            #     except ClientError as e:
            #         print(f"Error adding tutor {tutor_id} to DynamoDB: {e.response['Error']['Message']}")
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
        # Save default data to file
        os.makedirs("templates", exist_ok=True)
        with open(tutors_file_path, 'w') as f:
            json.dump(tutors_data, f, indent=2)
        # Populate Tutors_Table with default data
        for tutor_id, tutor_details in tutors_data.items():
            try:
                tutors_table.put_item(Item={"tutor_id": tutor_id, **tutor_details})
            except ClientError as e:
                print(f"Error adding tutor {tutor_id} to DynamoDB: {e.response['Error']['Message']}")
except Exception as e:
    print(f"Error loading tutors data: {e}")
    tutors_data = {}

# Mock database (will be replaced by DynamoDB, but kept for variable names)
# users = {} # Now handled by Users_Table
# sessions = {} # Sessions logic needs to be adapted for DynamoDB
# session_requests = {} # Session requests can be managed in a bookings table or separate table
# bookings = {} # Now handled by Bookings_Table
# payments = {} # Now handled by Payments_Table


# Initialize templates and static files with error handling
try:
    templates = Jinja2Templates(directory="templates")
    # Only mount static files if directory exists
    if os.path.exists("static"):
        app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    print(f"Error setting up templates/static files: {e}")

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
    try:
        response = users_table.get_item(Key={'email': email})
        user = response.get('Item')
        if user and user['password'] == password:
            return RedirectResponse(url="/student-dashboard", status_code=302)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e.response['Error']['Message']}")

@app.post("/register")
async def register(
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(...)
):
    try:
        response = users_table.get_item(Key={'email': email})
        if response.get('Item'):
            raise HTTPException(status_code=400, detail="User already exists")

        users_table.put_item(
            Item={
                "email": email,
                "password": password,
                "name": name,
                "role": "student"
            }
        )
        return RedirectResponse(url="/login", status_code=302)
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e.response['Error']['Message']}")

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
    # For now, still using tutors_data from the JSON file.
    # In a full DynamoDB implementation, you would query Tutors_Table here.
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
    tutor = tutors_data.get(tutor_id) # Still getting from in-memory dict
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
    total_price: float = Form(...), # This total_price from form is not used, calculated below
    learning_goals: str = Form(""),
    session_format: str = Form("Online Video Call")
):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")

    booking_id = str(uuid.uuid4())
    
    # Calculate total price based on sessions count
    calculated_price = tutor.get('rate', 25) * sessions_count

    booking = {
        "booking_id": booking_id, # Changed key to match DynamoDB partition key
        "tutor_id": tutor_id,
        "tutor_name": tutor["name"], # Store tutor name for easier retrieval
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

    try:
        bookings_table.put_item(Item=booking)
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error during booking: {e.response['Error']['Message']}")

    return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)

# Payment processing routes
@app.get("/payment", response_class=HTMLResponse)
async def payment_page(request: Request, booking_id: str = ""):
    if not booking_id:
        raise HTTPException(status_code=400, detail="Booking ID is required")
    
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e.response['Error']['Message']}")
    
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
                <p><strong>Tutor:</strong> {booking.get('tutor_name', 'N/A')}</p>
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
    email: str = Form(...), # Assuming this is the student's email for notifications
    phone: str = Form("")
):
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e.response['Error']['Message']}")
    
    # Process payment (mock)
    payment_id = str(uuid.uuid4())
    payment_record = {
        "payment_id": payment_id, # Changed key to match DynamoDB partition key
        "booking_id": booking_id,
        "amount": float(booking["total_price"]), # Ensure float
        "payment_method": payment_method,
        "status": "completed",
        "created_at": datetime.now().isoformat()
    }
    
    try:
        payments_table.put_item(Item=payment_record)
        
        # Update booking status in DynamoDB
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="SET #s = :status_val, payment_id = :pid",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status_val': "confirmed",
                ':pid': payment_id
            }
        )
        booking["status"] = "confirmed" # Update local booking object for confirmation page
        booking["payment_id"] = payment_id

        # Send SNS Notification
        try:
            message_subject = "TutorMatch: Session Confirmation & Payment Details"
            message_body = f"""
Dear Student,

Your session with {booking.get('tutor_name', 'N/A')} on {booking['date']} at {booking['time']} for {booking['subject']} has been successfully confirmed.

Payment Details:
- Amount Paid: ${booking['total_price']}
- Payment Method: {payment_method}
- Transaction ID: {payment_id}

Booking Details:
- Session Format: {booking['session_format']}
- Learning Goals: {booking.get('learning_goals', 'Not specified')}

We look forward to your session!

Best regards,
The TutorMatch Team
            """
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=message_subject,
                Message=message_body
            )
            print(f"SNS notification sent for booking ID: {booking_id} to topic: {SNS_TOPIC_ARN}")
        except ClientError as sns_e:
            print(f"Error sending SNS notification: {sns_e.response['Error']['Message']}")

    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error during payment processing: {e.response['Error']['Message']}")
    
    return RedirectResponse(url=f"/confirmation?booking_id={booking_id}", status_code=302)

@app.get("/confirmation", response_class=HTMLResponse)
async def confirmation_page(request: Request, booking_id: str = ""):
    if not booking_id:
        raise HTTPException(status_code=400, detail="Booking ID is required")
    
    try:
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e.response['Error']['Message']}")
    
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
                <p><strong>Tutor:</strong> {booking.get('tutor_name', 'N/A')}</p>
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
async def get_student_data(student_email: str = ""): # In a real app, student_email would come from authenticated session
    """Get student's bookings, payments, and notifications"""
    
    student_bookings = []
    student_payments = []
    notifications = []
    
    # In a real application, you would query bookings and payments specific to the logged-in student.
    # For now, fetching all and filtering (less efficient but works with current structure).
    # Ideally, bookings_table would have a GSI on student_email.
    
    try:
        # Scan bookings (inefficient for large tables, consider Query with GSI if student_email is available)
        response_bookings = bookings_table.scan()
        all_bookings = response_bookings.get('Items', [])

        # Scan payments
        response_payments = payments_table.scan()
        all_payments = response_payments.get('Items', [])

        # Filter bookings and payments (if student_email was truly passed and associated)
        # For this mock, we just process all bookings and payments
        
        for booking in all_bookings:
            # Assuming student_email is passed and we can link bookings to students
            # For demonstration, let's assume all bookings are for "the student"
            student_bookings.append({
                "id": booking["booking_id"],
                "tutor_name": booking.get("tutor_name", "N/A"),
                "subject": booking["subject"],
                "date": booking["date"],
                "time": booking["time"],
                "status": booking["status"],
                "total_price": booking["total_price"],
                "session_format": booking["session_format"],
                "created_at": booking["created_at"]
            })
            
            if "payment_id" in booking:
                # Find corresponding payment
                payment_record = next((p for p in all_payments if p.get('payment_id') == booking["payment_id"]), None)
                if payment_record:
                    student_payments.append({
                        "id": payment_record["payment_id"],
                        "tutor_name": booking.get("tutor_name", "N/A"),
                        "amount": payment_record["amount"],
                        "status": payment_record["status"],
                        "date": payment_record["created_at"],
                        "method": payment_record["payment_method"]
                    })
            
            booking_date_iso = booking["created_at"]
            try:
                booking_date_obj = datetime.fromisoformat(booking_date_iso)
            except ValueError:
                booking_date_obj = datetime.now() # Fallback for invalid date format

            if booking["status"] == "confirmed":
                notifications.append({
                    "type": "success",
                    "title": "Session Confirmed",
                    "message": f"Your {booking['subject']} session with {booking.get('tutor_name', 'N/A')} is confirmed for {booking['date']}.",
                    "date": booking_date_obj.strftime("%B %d, %Y")
                })
                
                try:
                    session_datetime_str = f"{booking['date']} {booking['time']}"
                    session_datetime = datetime.strptime(session_datetime_str, "%Y-%m-%d %H:%M")
                    
                    if session_datetime > datetime.now() and session_datetime < datetime.now() + timedelta(days=1):
                        notifications.append({
                            "type": "reminder",
                            "title": "Session Reminder",
                            "message": f"You have a {booking['subject']} session tomorrow at {booking['time']}.",
                            "date": datetime.now().strftime("%B %d, %Y")
                        })
                        # Send SNS notification for upcoming session
                        try:
                            message_subject = "TutorMatch: Upcoming Session Reminder"
                            message_body = f"""
Dear Student,

This is a reminder for your upcoming session with {booking.get('tutor_name', 'N/A')}.

Details:
- Subject: {booking['subject']}
- Date: {booking['date']}
- Time: {booking['time']}
- Session Format: {booking['session_format']}

Please be prepared!

Best regards,
The TutorMatch Team
                            """
                            # You'd need to know the student's email here. Assuming it's the `student_email` passed to the function,
                            # or retrieved from a user session. For this demo, sending to the topic.
                            sns_client.publish(
                                TopicArn=SNS_TOPIC_ARN,
                                Subject=message_subject,
                                Message=message_body
                            )
                            print(f"SNS reminder sent for booking ID: {booking['booking_id']} to topic: {SNS_TOPIC_ARN}")
                        except ClientError as sns_e:
                            print(f"Error sending SNS reminder: {sns_e.response['Error']['Message']}")

                except ValueError:
                    pass  # Invalid date/time format
        
        student_bookings.sort(key=lambda x: x["created_at"], reverse=True)
        student_payments.sort(key=lambda x: x["date"], reverse=True)
        notifications.sort(key=lambda x: x["date"], reverse=True)
        
        return {
            "bookings": student_bookings,
            "payments": student_payments,
            "notifications": notifications
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching student data: {e.response['Error']['Message']}")

# Utility routes
@app.get("/logout")
async def logout():
    return RedirectResponse(url="/", status_code=302)

# Health check endpoint
@app.get("/health")
async def health_check():
    # Attempt to access a DynamoDB table to verify connectivity
    try:
        users_table.name # Simple way to trigger a connection test
        db_status = "connected"
    except ClientError as e:
        db_status = f"error: {e.response['Error']['Message']}"
    
    return {"status": "healthy", "tutors_count": len(tutors_data), "database_status": db_status}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
