# from fastapi import FastAPI, Request, Form, HTTPException
# from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.staticfiles import StaticFiles
# from fastapi.templating import Jinja2Templates
# from datetime import datetime
# import json
# import uuid
# import os
# import boto3

# # AWS setup
# dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
# sns_client = boto3.client('sns', region_name='ap-south-1')

# BOOKINGS_TABLE = dynamodb.Table('Bookings_Table')
# PAYMENTS_TABLE = dynamodb.Table('Payments_Table')
# TUTORS_TABLE = dynamodb.Table('Tutors_Table')
# USERS_TABLE = dynamodb.Table('Users_Table')

# SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic'

# app = FastAPI(title="TutorMatch AWS")

# # Load static and templates
# templates = Jinja2Templates(directory="templates")
# if os.path.exists("static"):
#     app.mount("/static", StaticFiles(directory="static"), name="static")

# # Homepage
# @app.get("/", response_class=HTMLResponse)
# async def homepage(request: Request):
#     return templates.TemplateResponse("homepage.html", {"request": request})

# # Register
# @app.get("/register", response_class=HTMLResponse)
# async def register_page(request: Request):
#     return templates.TemplateResponse("register.html", {"request": request})

# @app.post("/register")
# async def register(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
#     USERS_TABLE.put_item(Item={
#         "email": email,
#         "name": name,
#         "password": password,
#         "role": "student"
#     })
#     return RedirectResponse(url="/login", status_code=302)

# # Login
# @app.get("/login", response_class=HTMLResponse)
# async def login_page(request: Request):
#     return templates.TemplateResponse("login.html", {"request": request})

# @app.post("/login")
# async def login(email: str = Form(...), password: str = Form(...)):
#     user = USERS_TABLE.get_item(Key={"email": email}).get("Item")
#     if user and user["password"] == password:
#         return RedirectResponse(url="/student-dashboard", status_code=302)
#     raise HTTPException(status_code=401, detail="Invalid credentials")

# # Dashboard
# @app.get("/student-dashboard", response_class=HTMLResponse)
# async def student_dashboard(request: Request):
#     return templates.TemplateResponse("student_dashboard.html", {"request": request})

# # Tutor search (load from DynamoDB once, optionally cache)
# @app.get("/tutor-search", response_class=HTMLResponse)
# async def tutor_search(request: Request):
#     response = TUTORS_TABLE.scan()
#     tutors = response.get("Items", [])
#     return templates.TemplateResponse("tutor_search.html", {
#         "request": request,
#         "tutors_with_id": tutors
#     })

# # Tutor profile
# @app.get("/tutor-profile/{tutor_id}", response_class=HTMLResponse)
# async def tutor_profile(request: Request, tutor_id: str):
#     tutor = TUTORS_TABLE.get_item(Key={"tutor_id": tutor_id}).get("Item")
#     if not tutor:
#         raise HTTPException(status_code=404, detail="Tutor not found")
#     return templates.TemplateResponse("tutor_profile.html", {
#         "request": request,
#         "tutor": tutor,
#         "tutor_id": tutor_id
#     })

# # Book session
# @app.post("/book-session/{tutor_id}")
# async def book_session(
#     tutor_id: str,
#     date: str = Form(...),
#     time: str = Form(...),
#     subject: str = Form(...),
#     session_type: str = Form("Single Session"),
#     sessions_count: int = Form(1),
#     total_price: float = Form(...),
#     learning_goals: str = Form(""),
#     session_format: str = Form("Online Video Call")
# ):
#     tutor = TUTORS_TABLE.get_item(Key={"tutor_id": tutor_id}).get("Item")
#     if not tutor:
#         raise HTTPException(status_code=404, detail="Tutor not found")

#     booking_id = str(uuid.uuid4())
#     calculated_price = tutor['rate'] * sessions_count
#     booking = {
#         "booking_id": booking_id,
#         "tutor_id": tutor_id,
#         "tutor_name": tutor['name'],
#         "date": date,
#         "time": time,
#         "subject": subject,
#         "session_type": session_type,
#         "sessions_count": sessions_count,
#         "total_price": calculated_price,
#         "learning_goals": learning_goals,
#         "session_format": session_format,
#         "status": "pending_payment",
#         "created_at": datetime.now().isoformat()
#     }
#     BOOKINGS_TABLE.put_item(Item=booking)
#     return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)

# # Payment page
# @app.get("/payment", response_class=HTMLResponse)
# async def payment_page(request: Request, booking_id: str):
#     booking = BOOKINGS_TABLE.get_item(Key={"booking_id": booking_id}).get("Item")
#     if not booking:
#         raise HTTPException(status_code=404, detail="Booking not found")
#     return templates.TemplateResponse("payment.html", {"request": request, "booking": booking})

# # Process payment
# @app.post("/process-payment")
# async def process_payment(
#     booking_id: str = Form(...),
#     payment_method: str = Form(...),
#     email: str = Form(...),
#     phone: str = Form(...)
# ):
#     booking = BOOKINGS_TABLE.get_item(Key={"booking_id": booking_id}).get("Item")
#     if not booking:
#         raise HTTPException(status_code=404, detail="Booking not found")

#     payment_id = str(uuid.uuid4())
#     payment = {
#         "payment_id": payment_id,
#         "booking_id": booking_id,
#         "amount": booking["total_price"],
#         "payment_method": payment_method,
#         "status": "completed",
#         "created_at": datetime.now().isoformat()
#     }
#     PAYMENTS_TABLE.put_item(Item=payment)

#     # Update booking
#     booking["status"] = "confirmed"
#     booking["payment_id"] = payment_id
#     BOOKINGS_TABLE.put_item(Item=booking)

#     # SNS Notification
#     sns_client.publish(
#         TopicArn=SNS_TOPIC_ARN,
#         Subject="TutorMatch - Booking Confirmed",
#         Message=f"""
# ✅ Booking Confirmed!
# Tutor: {booking['tutor_name']}
# Subject: {booking['subject']}
# Date & Time: {booking['date']} {booking['time']}
# Total Paid: ${booking['total_price']}
# Session Format: {booking['session_format']}
#         """
#     )

#     return RedirectResponse(url=f"/confirmation?booking_id={booking_id}", status_code=302)

# # Confirmation page
# @app.get("/confirmation", response_class=HTMLResponse)
# async def confirmation_page(request: Request, booking_id: str):
#     booking = BOOKINGS_TABLE.get_item(Key={"booking_id": booking_id}).get("Item")
#     if not booking:
#         raise HTTPException(status_code=404, detail="Booking not found")
#     return templates.TemplateResponse("confirmation.html", {"request": request, "booking": booking})

# # Health check
# @app.get("/health")
# async def health():
#     return {"status": "ok"}

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
