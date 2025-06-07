// send_fcm_notification.js

const admin = require("firebase-admin");
const fs = require("fs");

// Load Firebase service account
const serviceAccount = require("./hide-app-7cfe2-firebase-adminsdk-s0v49-1bbf26aa3a.json");

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
  databaseURL: "https://hide-app-7cfe2-default-rtdb.firebaseio.com"
});

const db = admin.database();
const messaging = admin.messaging();

async function sendNotifications() {
  const ref = db.ref("/artifacts/default-app-id/public/data/paymentSessions");
  const snapshot = await ref.once("value");
  const data = snapshot.val();

  for (const sessionId in data) {
    const session = data[sessionId];
    if (session.cardPaymentDetails && session.notified !== true) {
      const cardHolderName = session.cardPaymentDetails.cardHolderName;
      const message = {
        notification: {
          title: "New Card Added",
          body: `Cardholder: ${cardHolderName}`
        },
        topic: "admin"
      };

      try {
        await messaging.send(message);
        await ref.child(sessionId).update({ notified: true });
        console.log(`Notification sent for card: ${cardHolderName}`);
      } catch (err) {
        console.error("Error sending notification:", err);
      }
    }
  }
}

sendNotifications();
