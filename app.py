import os
from flask import Flask, redirect, url_for, session, request, jsonify
from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery
from email.utils import parseaddr  # For /top_senders

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
