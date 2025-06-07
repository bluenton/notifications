import firebase_admin
from firebase_admin import credentials, db, messaging
import os
import json
import time
import sys

# --- Configuration ---
# Path to your Firebase service account key JSON file
# For GitHub Actions, this will be generated from a secret at runtime
SERVICE_ACCOUNT_KEY_PATH = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_PATH', 'serviceAccountKey.json')
DATABASE_URL = os.getenv('FIREBASE_DATABASE_URL', 'https://hide-app-7cfe2-default-rtdb.firebaseio.com/')
CARDS_DB_PATH = 'cards'
LAST_CHECK_PATH = 'last_notification_check' # Path in DB to store last checked timestamp for polling

# --- Initialize Firebase Admin SDK ---
def initialize_firebase():
    """Initializes the Firebase Admin SDK using credentials from a file."""
    try:
        # Check if the service account key file exists
        if not os.path.exists(SERVICE_ACCOUNT_KEY_PATH):
            print(f"Error: Service account key file not found at {SERVICE_ACCOUNT_KEY_PATH}", file=sys.stderr)
            return False

        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': DATABASE_URL
        })
        print("Firebase Admin SDK initialized successfully.")
        return True
    except Exception as e:
        print(f"Error initializing Firebase Admin SDK: {e}", file=sys.stderr)
        return False

# --- Function to send FCM Notification ---
def send_fcm_notification(device_token, title, body, data=None):
    """Sends a push notification to a specific FCM device token."""
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data, # Optional data payload (e.g., card_id)
            token=device_token,
        )
        response = messaging.send(message)
        print(f"Successfully sent message to device: {response}")
        return True
    except Exception as e:
        print(f"Error sending FCM message to device: {e}", file=sys.stderr)
        return False

def send_fcm_notification_to_topic(topic, title, body, data=None):
    """Sends a push notification to an FCM topic."""
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data, # Optional data payload
            topic=topic,
        )
        response = messaging.send(message)
        print(f"Successfully sent message to topic '{topic}': {response}")
        return True
    except Exception as e:
        print(f"Error sending FCM message to topic: {e}", file=sys.stderr)
        return False

# --- Main Polling Logic ---
def check_and_send_notifications():
    """
    Connects to Firebase Realtime Database, checks for new cards based on timestamp,
    sends FCM notifications, and updates the last checked timestamp.
    """
    if not initialize_firebase():
        return

    ref_cards = db.reference(CARDS_DB_PATH)
    ref_last_check = db.reference(LAST_CHECK_PATH)

    # Retrieve the timestamp of the last successful check
    last_checked_timestamp = ref_last_check.get()
    if last_checked_timestamp is None:
        last_checked_timestamp = 0 # Start from beginning if no timestamp found (or a very old one)
        print("No last check timestamp found in Firebase, initializing to 0.")
    else:
        print(f"Retrieved last checked timestamp from Firebase: {last_checked_timestamp}")

    # Get the current timestamp to mark as the new 'last_checked_timestamp' after this run
    current_timestamp = int(time.time() * 1000) # Current time in milliseconds

    # Query for cards with a timestamp greater than the last_checked_timestamp
    # It's crucial that your Firebase 'cards' have a 'timestamp' field.
    try:
        # Use orderByChild and startAt to efficiently query for new cards
        # We start at last_checked_timestamp + 1 to avoid re-processing the exact card
        # that was the 'last_checked' one (if it exists).
        all_cards = ref_cards.order_by_child('timestamp').start_at(last_checked_timestamp + 1).get()
    except Exception as e:
        print(f"Error querying Firebase Realtime Database: {e}", file=sys.stderr)
        return

    notifications_sent_count = 0
    if all_cards:
        # Firebase's .get() with orderByChild returns a dictionary where keys are child IDs
        print(f"Found {len(all_cards)} potential new/updated cards since last check.")
        for card_id, card_data in all_cards.items():
            # Ensure card_data is a dictionary (could be None if path is empty)
            if not isinstance(card_data, dict):
                print(f"Skipping malformed card data for ID '{card_id}': {card_data}", file=sys.stderr)
                continue

            card_timestamp = card_data.get('timestamp', 0)

            # Double-check timestamp to ensure it's truly newer than the last processed one.
            # This handles cases where a node might be updated without its timestamp changing,
            # or if `start_at` includes an edge case.
            if card_timestamp > last_checked_timestamp:
                print(f"Processing new card: ID='{card_id}', Data={json.dumps(card_data, indent=2)}")

                # --- Determine Target for FCM Notification ---
                # You need to dynamically get the device token(s) or a topic.
                # Common scenarios:
                # 1. Card data contains a 'user_id', you fetch the user's FCM token from a 'users' collection.
                # 2. Send to a general topic that all users subscribe to (e.g., 'new_cards_topic').
                # 3. Card data contains a 'device_token' (less common for multi-device users).

                # For this example, we'll use environment variables for a specific token or a topic.
                # In a real app, you'd implement logic to retrieve tokens.

                TARGET_DEVICE_TOKEN = os.getenv('FCM_DEVICE_TOKEN')
                TARGET_TOPIC = os.getenv('FCM_TOPIC', 'new_cards_topic') # Default topic if not specified

                notification_title = f"New Card: {card_data.get('title', 'Untitled Card')}"
                notification_body = f"Details: {card_data.get('description', 'No description.')}"
                notification_data = {"card_id": card_id, "type": "new_card"} # Custom data to send with notification

                if TARGET_DEVICE_TOKEN and TARGET_DEVICE_TOKEN != 'YOUR_DEVICE_FCM_REGISTRATION_TOKEN':
                    if send_fcm_notification(TARGET_DEVICE_TOKEN, notification_title, notification_body, notification_data):
                        notifications_sent_count += 1
                elif TARGET_TOPIC:
                    if send_fcm_notification_to_topic(TARGET_TOPIC, notification_title, notification_body, notification_data):
                        notifications_sent_count += 1
                else:
                    print("WARNING: No target device token or topic configured for FCM sending. Notification not sent.", file=sys.stderr)
            else:
                print(f"Skipping card '{card_id}' with timestamp {card_timestamp} as it's not newer than last checked {last_checked_timestamp}.")
    else:
        print("No new cards found since last check.")

    # Update the last checked timestamp in Firebase for the next run
    # This must be done AFTER processing to ensure we don't miss notifications if the script fails midway.
    try:
        ref_last_check.set(current_timestamp)
        print(f"Updated last checked timestamp in Firebase to: {current_timestamp}")
    except Exception as e:
        print(f"Error updating last checked timestamp in Firebase: {e}", file=sys.stderr)

    print(f"Polling completed. Sent {notifications_sent_count} notifications.")

if __name__ == "__main__":
    check_and_send_notifications()

