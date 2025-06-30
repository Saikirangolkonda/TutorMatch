import boto3
from datetime import datetime
import uuid

dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
table = dynamodb.Table("Users_Table")

item = {
    "email": "test@example.com",
    "password": "test123",
    "name": "Test User",
    "role": "student",
    "created_at": datetime.now().isoformat()
}

table.put_item(Item=item)
print("User inserted successfully.")
