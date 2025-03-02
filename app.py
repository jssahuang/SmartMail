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
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

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
