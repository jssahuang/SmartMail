import os
from flask import Flask, redirect, url_for, session, request, jsonify
from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery
from email.utils import parseaddr  # For /top_senders
from google import genai
import json
import re  # Import the re module

app = Flask(__name__)
app.secret_key = "your-secret-key"  # Use a stable, fixed secret key

CLIENT_SECRETS_FILE = "client_secret_1094721022736-rmc636sgd1jd636lq6v4pi3n2hor7je4.apps.googleusercontent.com.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly"
]

def get_credentials():
    """Return Google API credentials using either the session or the Authorization header."""
    # First, try to get the token from the Authorization header.
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split("Bearer ")[1]
        # Construct credentials from the token.
        return google.oauth2.credentials.Credentials(token)
    
    # Otherwise, try the session.
    if "credentials" in session:
        return google.oauth2.credentials.Credentials(**session["credentials"])
    
    # If neither is present, return None.
    return None

@app.route("/")
def index():
    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))
    
    service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])
    
    # Optionally update session credentials (if using session)
    if "credentials" in session:
        session["credentials"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
    
    return jsonify(labels)

@app.route("/top_senders", methods=["GET"])
def top_senders():
    # Get date from query params.
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Please provide a date using '?date=YYYY-MM-DD'"}), 400

    try:
        year, month, day = date_str.split("-")
    except ValueError:
        return jsonify({"error": "Date format should be YYYY-MM-DD"}), 400

    gmail_date = f"{year}/{month}/{day}"
    query = f"is:unread after:{gmail_date}"
    limit = request.args.get("limit", 10, type=int)

    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))
    
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)
    sender_counts = {}
    sender_names = {}
    page_token = None

    while True:
        response = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=100,
            pageToken=page_token
        ).execute()

        messages = response.get("messages", [])
        for message in messages:
            msg_id = message["id"]
            msg = service.users().messages().get(
                userId="me", id=msg_id,
                format="metadata",
                metadataHeaders=["From"]
            ).execute()
            headers = msg.get("payload", {}).get("headers", [])
            from_value = None
            for header in headers:
                if header["name"].lower() == "from":
                    from_value = header["value"]
                    break
            if from_value:
                name, email_address = parseaddr(from_value)
                sender_counts[email_address] = sender_counts.get(email_address, 0) + 1
                if email_address not in sender_names:
                    sender_names[email_address] = name if name else email_address
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    top_senders_list = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    result = []
    for email_address, count in top_senders_list:
        result.append({
            "email": email_address,
            "name": sender_names.get(email_address, email_address),
            "unread_count": count
        })

    # Update session credentials if applicable.
    if "credentials" in session:
        session["credentials"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }

    return jsonify(result)

@app.route("/trash_emails", methods=["GET"])
def trash_emails():
    """
    Trashes all emails from a specified sender.
    Example usage: /trash_emails?sender=user@example.com
    """
    # Get the sender email from the query parameters
    sender = request.args.get("sender")
    if not sender:
        return jsonify({"error": "Please provide a sender email using '?sender=...'"}), 400

    # Use the helper to get credentials (checks header first, then session)
    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))
    
    # Build the Gmail service with the obtained credentials.
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)
    
    # Build the search query for emails from the specified sender.
    query = f"from:{sender}"
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])
    
    if not messages:
        return jsonify({"message": f"No emails found from {sender}."})
    
    trashed_count = 0
    # Loop through the messages and trash each one.
    for message in messages:
        msg_id = message["id"]
        service.users().messages().trash(userId="me", id=msg_id).execute()
        trashed_count += 1

    # (Optionally) Update session credentials if they exist.
    if "credentials" in session:
        session["credentials"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
    
    return jsonify({"message": f"Trashed {trashed_count} emails from {sender}."})

@app.route("/mark_as_read", methods=["GET"])
def mark_as_read():
    """
    Marks all emails from a specified sender as read.
    Example usage: /mark_as_read?sender=user@example.com
    """
    # Get the sender email from the query parameters.
    sender = request.args.get("sender")
    if not sender:
        return jsonify({"error": "Please provide a sender email using '?sender=...'"}), 400

    # Get credentials (checks header then session).
    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))
    
    # Build the Gmail service.
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)
    
    # Build the query to find unread emails from the sender.
    query = f"from:{sender} is:unread"
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])
    
    if not messages:
        return jsonify({"message": f"No unread emails found from {sender}."})

    marked_count = 0
    # Loop through the messages and mark each one as read.
    for message in messages:
        msg_id = message["id"]
        modify_body = {
            "removeLabelIds": ["UNREAD"]
        }
        service.users().messages().modify(userId="me", id=msg_id, body=modify_body).execute()
        marked_count += 1

    # Optionally update session credentials.
    if "credentials" in session:
        session["credentials"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }

    return jsonify({"message": f"Marked {marked_count} emails from {sender} as read."})

@app.route("/trash_email_by_id", methods=["GET"])
def trash_email_by_id():
    """
    Moves a single email (specified by its Gmail message ID) to the Trash.
    Example usage: /trash_email_by_id?email_id=abc123xyz
    """
    # 1. Get the email_id from query parameters
    email_id = request.args.get("email_id")
    print(f"Email ID to trash: {email_id}")
    if not email_id:
        return jsonify({"error": "Please provide an email_id using '?email_id=...'" }), 400

    # 2. Get credentials
    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))

    # 3. Build the Gmail service
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)

    # 4. Check if the email exists
    try:
        email = service.users().messages().get(userId="me", id=email_id).execute()
        print(f"Email found: {email}")
    except googleapiclient.errors.HttpError as e:
        print(f"Error retrieving email: {e}")
        return jsonify({"error": "Failed to retrieve the email.", "details": str(e)}), 400

    # 5. Trash the specific email
    try:
        response = service.users().messages().trash(userId="me", id=email_id).execute()
        print(f"Trash response: {response}")
        return jsonify({"message": f"Email with ID {email_id} has been moved to trash."})
    except googleapiclient.errors.HttpError as e:
        # If the message doesn't exist or there's another Gmail API error
        print(f"Error trashing email: {e}")
        return jsonify({"error": "Failed to trash the email.", "details": str(e)}), 400


@app.route("/mark_email_as_read_by_id", methods=["GET"])
def mark_email_as_read_by_id():
    """
    Marks a single email (specified by its Gmail message ID) as read.
    Example usage: /mark_email_as_read_by_id?email_id=abc123xyz
    """
    # 1. Get the email_id from query parameters
    email_id = request.args.get("email_id")
    if not email_id:
        return jsonify({"error": "Please provide an email_id using '?email_id=...'" }), 400

    # 2. Get credentials
    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))

    # 3. Build the Gmail service
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)

    # 4. Mark the email as read by removing the UNREAD label
    try:
        modify_body = {
            "removeLabelIds": ["UNREAD"]
        }
        service.users().messages().modify(userId="me", id=email_id, body=modify_body).execute()
        return jsonify({"message": f"Email with ID {email_id} has been marked as read."})
    except googleapiclient.errors.HttpError as e:
        return jsonify({"error": "Failed to mark the email as read.", "details": str(e)}), 400

@app.route("/prioritize_emails", methods=["GET"])
def prioritize_emails():
    """
    Prioritizes emails from a specified sender that are unread and received after a given date.
    It calls the Gemini API for each email's subject to get a priority rating (1-10) and returns
    the top 10 emails with their subject, email ID, and priority.
    
    Example usage: /prioritize_emails?sender=user@example.com&date=2024-01-01
    """
    # Get parameters from query string.
    sender_param = request.args.get("sender")
    date_str = request.args.get("date")
    if not sender_param or not date_str:
        return jsonify({"error": "Please provide both 'sender' and 'date' (YYYY-MM-DD) parameters."}), 400

    try:
        year, month, day = date_str.split("-")
    except ValueError:
        return jsonify({"error": "Date format should be YYYY-MM-DD"}), 400

    # Construct Gmail query. (You might also exclude trash if needed, e.g., add "-in:trash")
    gmail_date = f"{year}/{month}/{day}"
    query = f"from:{sender_param} is:unread after:{gmail_date}"
    
    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))
    
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)
    emails = []
    page_token = None

    # Retrieve all messages matching the query.
    while True:
        response = service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()
        messages = response.get("messages", [])
        emails.extend(messages)
        if len(emails) >= 20:
            emails = emails[:20]  # Cap to 20 messages.
            break
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    if not emails:
        return jsonify({"message": f"No unread emails found from {sender_param} after {date_str}."})
    
    prioritized_emails = []
    emailList = []
    # Process each email: get its subject and compute priority.
    for message in emails:
        msg_id = message["id"]
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="metadata", metadataHeaders=["Subject"]
        ).execute()
        headers = msg.get("payload", {}).get("headers", [])
        subject = ""
        for header in headers:
            if header["name"].lower() == "subject":
                subject = header["value"]
                break
        emailList.append({"email_id": msg_id, "subject": subject})
   
    # Call the Gemini API to get the priority for each email.
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Given a list of " + str(len(emailList)) + " emails, prioritize them based on their subject line, where 10 is a really important email that should be responded to immediately and 1 is most likely to be spam cluttering your inbox. Return the top 10 emails with their subject, email ID, and priority in JSON format with keys email_id unmodified, subject, and priority: " + str(emailList) + "Do not include anything else in the response besides the JSON object.",
        )
    
    response_content = response.text  # Adjust this line based on the actual response structure
    print("Response content:", response_content)  # Debugging line

    # Check if the response content is empty
    if not response_content:
        print("Received empty response from the Gemini API.")
        return jsonify({"error": "Received empty response from the Gemini API"}), 500

    try:
        # Use a regular expression to extract the JSON substring
        json_match = re.search(r'(\[.*\])', response_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            prioritized_emails = json.loads(json_str)  # Parse the JSON response
        else:
            print("Failed to extract JSON from response because the regular expression did not match.")
            return jsonify({"error": "Failed to extract JSON from response"}), 500
    except json.JSONDecodeError as e:
        print("Failed to parse JSON response:", e)
        return jsonify({"error": "Failed to parse JSON response", "details": str(e)}), 500

    # Sort emails by priority descending (highest priority first)
    prioritized_emails.sort(key=lambda x: x["priority"], reverse=True)
    
    # Optionally update session credentials.
    if "credentials" in session:
        session["credentials"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
    
    return jsonify(prioritized_emails)


    """
    Moves a single email (specified by its Gmail message ID) to the Trash.
    Example usage: /trash_email_by_id?email_id=abc123xyz
    """
    # 1. Get the email_id from query parameters
    email_id = request.args.get("email_id")
    print(f"Email ID to trash: {email_id}")
    if not email_id:
        return jsonify({"error": "Please provide an email_id using '?email_id=...'" }), 400

    # 2. Get credentials
    creds = get_credentials()
    if creds is None:
        return redirect(url_for("authorize"))

    # 3. Build the Gmail service
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)

    # 4. Trash the specific email
    try:
        response = service.users().messages().trash(userId="me", id=email_id).execute()
        print(f"Trash response: {response}")
        return jsonify({"message": f"Email with ID {email_id} has been moved to trash."})
    except googleapiclient.errors.HttpError as e:
        # If the message doesn't exist or there's another Gmail API error
        print(f"Error trashing email: {e}")
        return jsonify({"error": "Failed to trash the email.", "details": str(e)}), 400
@app.route("/authorize")
def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session["state"] = state
    return redirect(authorization_url)

@app.route("/oauth2callback")
def oauth2callback():
    state = session["state"]
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session["credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
    # Redirect to the frontend with the token.
    frontend_url = "http://localhost:8501"
    
    return redirect(f"{frontend_url}?access_token={credentials.token}")

@app.route("/clear")
def clear_credentials():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run("localhost", 8080, debug=True)