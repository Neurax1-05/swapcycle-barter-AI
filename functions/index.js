const { beforeUserCreated, beforeUserSignedIn } = require("firebase-functions/v2/identity");
const { HttpsError } = require("firebase-functions/v2/https");

const ALLOWED_DOMAIN = "qiu.edu.my";

function assertAllowedDomain(email) {
  if (!email || !email.toLowerCase().endsWith(`@${ALLOWED_DOMAIN}`)) {
    // Thrown here = Firebase Auth blocks the sign-up/sign-in entirely,
    // before a user record is even created. This is the real boundary —
    // everything on the Flutter side is just a nicer error message.
    throw new HttpsError(
      "permission-denied",
      `Only @${ALLOWED_DOMAIN} accounts may use SwapCycle.`
    );
  }
}

// Fires on every new account creation (email/password sign-up, first
// Google sign-in, etc.)
exports.restrictSignUpDomain = beforeUserCreated((event) => {
  assertAllowedDomain(event.data.email);
});

// Fires on every sign-in, including returning users — covers the case
// where an account somehow already exists with a non-QIU email.
exports.restrictSignInDomain = beforeUserSignedIn((event) => {
  assertAllowedDomain(event.data.email);
});
