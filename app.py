import boto3

dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
table = dynamodb.Table('Tutors')

tutor_data = {
    'tutor_id': '6',
    'name': 'Alex Turner',
    'subjects': ['Biology', 'Chemistry'],
    'rate': 40,
    'rating': 4.9,
    'bio': 'Expert in Biology and Chemistry with 10 years of teaching experience.',
    'availability': ['Monday 10-18', 'Thursday 9-17']
}

table.put_item(Item=tutor_data)
print("Tutor with ID 6 added.")
