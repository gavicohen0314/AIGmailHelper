from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os.path
import redis

# Define the SCOPES. If modifying it, delete the token.pickle file.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def getEmails():
    email_dict = {}
    creds = None  # variable to store user credentials

    # Check if a user token file already exists
    if os.path.exists('token.pickle'):
        # Read and store user credentials
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    # If there are no valid credentials, request from the user to log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the access token in token.pickle file
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    # Connect to the Gmail API
    service = build('gmail', 'v1', credentials=creds)

    # request the last 100 emails
    result = service.users().messages().list(maxResults=10, userId='me').execute()
    messages = result.get('messages')  # dictionary of the last 100 emails ids

    for email in messages:
        # Get the email from its id
        email_id = email['id']
        email_data = service.users().messages().get(userId='me', id=email_id).execute()

        try:
            payload = email_data['payload']
            headers = payload['headers']

            # Extract subject (if it exists) and sender
            for d in headers:
                if d['name'] == 'Subject':
                    subject = d['value']
                if d['name'] == 'From':
                    sender = d['value']

            email_dict[email_id] = {"sender": sender, "subject": subject}
        except Exception:
            pass

    return email_dict


def main():
    # Connect to the Redis server
    # Make sure to run the following command before running the script:
    # docker run -d --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
    redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

    # Test the connection
    try:
        redis_client.ping()
        print("Connected to Redis!")
        redis_active = True
    except redis.ConnectionError as e:
        print(f"Failed to connect to Redis: {e}")
        redis_active = False

    email_dict = getEmails()
    print(redis_active)
    print(email_dict)


if __name__ == "__main__":
    main()
