import os
from flask import Flask, redirect, url_for, session, request, jsonify
from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery

app = Flask(__name__)
app.secret_key = "your-secret-key"  # Replace with a secure key in production

# Path to your client_secret.json file
CLIENT_SECRETS_FILE = "client_secret_1094721022736-rmc636sgd1jd636lq6v4pi3n2hor7je4.apps.googleusercontent.com.json"

# Define the scopes your app requires
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly"
]


@app.route("/")
def index():
    if "credentials" not in session:
        return redirect(url_for("authorize"))
    
    # Load credentials from the session.
    credentials = google.oauth2.credentials.Credentials(**session["credentials"])
    service = googleapiclient.discovery.build('gmail', 'v1', credentials=credentials)
    
    # Example API call: List Gmail labels
    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])
    
    # Optionally, update the session credentials in case of token refresh
    session["credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
    
    return jsonify(labels)

@app.route("/trash_emails", methods=["GET"])
def trash_emails():
    sender = request.args.get("sender")
    if not sender:
        return jsonify({"error": "Please provide a sender email using '?sender=...'"}), 400

    if "credentials" not in session:
        return redirect(url_for("authorize"))

    credentials = google.oauth2.credentials.Credentials(**session["credentials"])
    service = googleapiclient.discovery.build("gmail", "v1", credentials=credentials)
    
    trashed_count = 0
    query = f"from:{sender}"
    page_token = None

    while True:
        response = service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()
        
        messages = response.get("messages", [])
        for message in messages:
            msg_id = message["id"]
            service.users().messages().trash(userId="me", id=msg_id).execute()
            trashed_count += 1
        
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    session["credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }

    return jsonify({"message": f"Trashed {trashed_count} emails from {sender}."})

@app.route("/move_emails", methods=["GET"])
def move_emails():
    """
    Moves all emails from the inbox whose subject contains a certain string 
    to a custom folder (label). The operation is done by removing the INBOX 
    label and adding the custom label.
    
    Example usage: /move_emails?subject=Meeting&folder=Meetings
    If folder is not provided, a default folder name will be used.
    """
    # Get the subject string and folder name from query parameters.
    subject_query = request.args.get("subject")
    if not subject_query:
        return jsonify({"error": "Please provide a subject string using '?subject=...'"}), 400

    # Use provided folder name or default to "Emails with '<subject>'"
    folder_name = request.args.get("folder", f"Emails with '{subject_query}'")

    # Ensure the user is authenticated.
    if "credentials" not in session:
        return redirect(url_for("authorize"))

    # Load credentials and build the Gmail service.
    credentials = google.oauth2.credentials.Credentials(**session["credentials"])
    service = googleapiclient.discovery.build("gmail", "v1", credentials=credentials)

    # --- Step 1: Get or Create the Custom Label (Folder) ---
    # List existing labels.
    labels_response = service.users().labels().list(userId="me").execute()
    labels = labels_response.get("labels", [])
    label_id = None
    for label in labels:
        if label.get("name") == folder_name:
            label_id = label.get("id")
            break
    # If label does not exist, create it.
    if not label_id:
        label_body = {
            "name": folder_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show"
        }
        created_label = service.users().labels().create(userId="me", body=label_body).execute()
        label_id = created_label.get("id")

    # --- Step 2: Find and Process Messages ---
    # Build the search query. This limits results to messages in INBOX and with the given subject.
    query = f"in:inbox subject:{subject_query}"
    moved_count = 0
    page_token = None

    while True:
        response = service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()
        messages = response.get("messages", [])
        for message in messages:
            msg_id = message["id"]
            # Modify the message: remove "INBOX" and add the custom label.
            modify_body = {
                "removeLabelIds": ["INBOX"],
                "addLabelIds": [label_id]
            }
            service.users().messages().modify(userId="me", id=msg_id, body=modify_body).execute()
            moved_count += 1
        
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    # Optionally, update session credentials in case of token refresh.
    session["credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }

    return jsonify({"message": f"Moved {moved_count} emails to folder '{folder_name}'."})



@app.route("/authorize")
def authorize():
    # Set up the OAuth 2.0 Flow instance
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
    
    # Store credentials in the session
    session["credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
    
    return redirect(url_for("index"))

@app.route("/clear")
def clear_credentials():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run("localhost", 8080, debug=True)
