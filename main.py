from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from datetime import datetime, timedelta
import json
import uuid
import os
import boto3
from botocore.exceptions import ClientError

app = FastAPI(title="TutorMatch")

# AWS setup
region = "ap-south-1"
dynamodb = boto3.resource('dynamodb', region_name=region)
sns = boto3.client('sns', region_name=region)

bookings_table = dynamodb.Table('Bookings_Table')
payments_table = dynamodb.Table('Payments_Table')
users_table = dynamodb.Table('Users_Table')
SNS_TOPIC_ARN = "arn:aws:sns:ap-south-1:686255965861:TutorBookingTopic"

# Load tutor data
try:
    tutors_file_path = os.path.join("templates", "tutors_data.json")
    if os.path.exists(tutors_file_path):
        with open(tutors_file_path) as f:
            tutors_data = json.load(f)
    else:
        tutors_data = {}
except:
    tutors_data = {}

# Templates
templates = Jinja2Templates(directory="templates")
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("homepage.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(email: str = Form(...), password: str = Form(...), name: str = Form(...)):
    try:
        users_table.put_item(Item={
            "email": email,
            "password": password,
            "name": name,
            "role": "student"
        })
        return RedirectResponse(url="/login", status_code=302)
    except ClientError:
        raise HTTPException(status_code=400, detail="User already exists or DB error")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    try:
        response = users_table.get_item(Key={"email": email})
        user = response.get("Item")
        if user and user["password"] == password:
            return RedirectResponse(url="/student-dashboard", status_code=302)
    except ClientError:
        pass
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/student-dashboard", response_class=HTMLResponse)
async def student_dashboard(request: Request):
    return templates.TemplateResponse("student_dashboard.html", {"request": request})

@app.get("/tutor-search", response_class=HTMLResponse)
async def tutor_search(request: Request):
    return templates.TemplateResponse("tutor_search.html", {
        "request": request,
        "tutors_with_id": [{"id": k, **v} for k, v in tutors_data.items()]
    })

@app.get("/tutor-profile/{tutor_id}", response_class=HTMLResponse)
async def tutor_profile(request: Request, tutor_id: str):
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")
    return templates.TemplateResponse("tutor_profile.html", {
        "request": request,
        "tutor": tutor,
        "tutor_id": tutor_id
    })

@app.post("/book-session/{tutor_id}")
async def book_session(
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
    tutor = tutors_data.get(tutor_id)
    if not tutor:
        raise HTTPException(status_code=404, detail="Tutor not found")

    booking_id = str(uuid.uuid4())
    calculated_price = tutor.get('rate', 25) * sessions_count
    booking = {
        "booking_id": booking_id,
        "tutor_id": tutor_id,
        "tutor_name": tutor['name'],
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
    except ClientError:
        raise HTTPException(status_code=500, detail="Failed to save booking")

    return RedirectResponse(url=f"/payment?booking_id={booking_id}", status_code=302)

@app.get("/payment", response_class=HTMLResponse)
async def payment_page(request: Request, booking_id: str):
    return templates.TemplateResponse("payment.html", {"request": request, "booking_id": booking_id})

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
        booking_response = bookings_table.get_item(Key={"booking_id": booking_id})
        booking = booking_response.get("Item")
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        payment_id = str(uuid.uuid4())

        payments_table.put_item(Item={
            "payment_id": payment_id,
            "booking_id": booking_id,
            "amount": booking["total_price"],
            "payment_method": payment_method,
            "status": "completed",
            "created_at": datetime.now().isoformat()
        })

        bookings_table.update_item(
            Key={"booking_id": booking_id},
            UpdateExpression="SET #s = :status, payment_id = :pid",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": "confirmed", ":pid": payment_id}
        )

        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="New Booking Confirmed",
            Message=f"Booking confirmed for {booking['tutor_name']} on {booking['date']} at {booking['time']}"
        )

        return RedirectResponse(url=f"/confirmation?booking_id={booking_id}", status_code=302)

    except ClientError:
        raise HTTPException(status_code=500, detail="Payment or SNS error")

@app.get("/confirmation", response_class=HTMLResponse)
async def confirmation_page(request: Request, booking_id: str):
    return templates.TemplateResponse("confirmation.html", {"request": request, "booking_id": booking_id})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
