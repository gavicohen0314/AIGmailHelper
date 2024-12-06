from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os.path
import redis
from gpt4all import GPT4All
import pandas as pd
import ast
import matplotlib.pyplot as plt
from wordcloud import WordCloud


# Define the SCOPES. If modifying it, delete the token.pickle file.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def getEmails(numResults):
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
    result = service.users().messages().list(maxResults=numResults, userId='me').execute()
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


def processEmails(redis_client):
    email_data = {}
    for key in redis_client.scan_iter():
        email_data[key] = ast.literal_eval(redis_client.get(key))

        # Convert to DataFrame
    df = pd.DataFrame.from_dict(email_data, orient='index')
    # Extract email addresses using regex
    df['email'] = df['sender'].str.extract(r'<([^>]+)>')

    # Remove the full name from the 'sender' column, keeping only the email
    df['sender'] = df['email']

    # Convert multiple columns to lowercase
    columns_to_lower = ['category', 'priority', 'respond']
    df[columns_to_lower] = df[columns_to_lower].apply(lambda x: x.str.lower())

    # Create a figure with a grid of subplots (3 rows, 3 columns)
    fig, ax = plt.subplots(2, 3, figsize=(15, 8))  # Adjust size for readability

    # Plot 1: Pie Chart of Email Categories
    category_counts = df["category"].value_counts()
    ax[0, 0].pie(category_counts, labels=category_counts.index, autopct='%1.1f%%', startangle=140)
    ax[0, 0].set_title("Distribution of Email Categories")

    # Plot 2: Bar Chart of Email Priorities
    priority_counts = df["priority"].value_counts()
    priority_counts.plot(kind="bar", ax=ax[0, 1], color='skyblue')
    ax[0, 1].set_title("Email Priority Distribution")
    ax[0, 1].set_xlabel("Priority")
    ax[0, 1].set_ylabel("Count")
    ax[0, 1].tick_params(axis='x', rotation=0)

    # Plot 3: Stacked Bar Chart of Categories by Priority
    category_priority = df.groupby(["category", "priority"]).size().unstack(fill_value=0)
    category_priority.plot(kind="bar", stacked=True, ax=ax[0, 2], colormap='viridis')
    ax[0, 2].set_title("Categories by Priority")
    ax[0, 2].set_xlabel("Category")
    ax[0, 2].set_ylabel("Count")
    ax[0, 2].legend(title="Priority")
    ax[0, 2].tick_params(axis='x', rotation=0)

    # Plot 4: Bar Chart of Top Senders
    top_senders = df["sender"].value_counts().head(10)
    top_senders.plot(kind="barh", ax=ax[1, 0], color='orange')
    ax[1, 0].set_title("Top Senders")
    ax[1, 0].set_xlabel("Count")
    ax[1, 0].set_ylabel("Sender")
    ax[1, 0].invert_yaxis()  # Flip order for better visualization

    # Plot 5: Word Cloud of Email Subjects
    # Preprocess to remove Hebrew characters from the 'subject' column
    text = " ".join(df["subject"].str.replace(r'[\u0590-\u05FF]', '', regex=True))
    wordcloud = WordCloud(width=800, height=400, background_color="white").generate(text)
    ax[1, 1].imshow(wordcloud, interpolation="bilinear")
    ax[1, 1].axis("off")  # Remove axes for word cloud
    ax[1, 1].set_title("Common Words in Email Subjects")

    # Plot 6: Bar Chart of Needs Response by Category
    response_data = df.groupby(["category", "respond"]).size().unstack(fill_value=0)
    response_data.plot(kind="bar", ax=ax[1, 2], colormap='cool')
    ax[1, 2].set_title("Needs Response by Category")
    ax[1, 2].set_xlabel("Category")
    ax[1, 2].set_ylabel("Count")
    ax[1, 2].legend(title="Needs Response")
    ax[1, 2].tick_params(axis='x', rotation=0)

    # Adjust layout
    plt.tight_layout()
    plt.show()


def main():
    # Connect to the Redis server
    # Make sure to run the following command before running the script:
    # docker run -d --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
    redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

    # Test the connection
    try:
        redis_client.ping()
        print("Connected to Redis!")
    except redis.ConnectionError as e:
        print(f"Failed to connect to Redis: {e}")
        return

    # we check how many emails are already stored in the database, and process x more to get us to 100 emails
    num_curr_emails = redis_client.dbsize()
    if num_curr_emails < 100:
        email_dict = getEmails(100-num_curr_emails)
        print(100-num_curr_emails)

        # initialize model
        model = GPT4All(model_name='Meta-Llama-3-8B-Instruct.Q4_0.gguf')

        for email_id in email_dict:
            if not redis_client.exists(email_id):
                sender = email_dict[email_id]["sender"]
                subject = email_dict[email_id]["subject"]
                prompt = f'''Classify the following email as one of the following categories (Work, School, Shopping, Entertainment, Other). Return only a single word output, no explanations or notes. Here is the email:
Subject: "{subject}"
Sender: "{sender}"
'''
                with model.chat_session():
                    category = model.generate(prompt, max_tokens=8, temp=0.3)
                prompt = f'''Classify the following email as one of the following priorities (Urgent, Important, Normal). Return only a single word output, no explanations or notes. Here is the email:
Subject: "{subject}"
Sender: "{sender}"
'''
                with model.chat_session():
                    priority = model.generate(prompt, max_tokens=8, temp=0.3)
                prompt = f'''Decide if I need to respond to the following email (Yes/No). Return only a single word output, no explanations or notes. Here is the email:
Subject: "{subject}"
Sender: "{sender}"
'''
                with model.chat_session():
                    respond = model.generate(prompt, max_tokens=8, temp=0.3)
                redis_client.setex(name=email_id, value=str({"sender": sender, "subject": subject, "category": category, "priority": priority, "respond": respond}), time=3600*4)

    processEmails(redis_client)


if __name__ == "__main__":
    main()
