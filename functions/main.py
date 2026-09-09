from firebase_functions import identity_fn
from firebase_functions.identity_fn import (
    AuthBlockingEvent,
    BeforeCreateResponse,
    BeforeSignInResponse,
    HttpsError,
)

ALLOWED_DOMAIN = "qiu.edu.my"


def _assert_allowed_domain(email: str | None) -> None:
    if not email or not email.lower().endswith(f"@{ALLOWED_DOMAIN}"):
        # Raising here blocks the sign-up/sign-in entirely, before any
        # user record is created. This is the real enforcement boundary —
        # everything on the Flutter side is just a nicer error message.
        raise HttpsError(
            code="permission-denied",
            message=f"Only @{ALLOWED_DOMAIN} accounts may use SwapCycle.",
        )


# Fires on every new account creation (email/password sign-up, first
# Google sign-in, etc.)
@identity_fn.before_user_created()
def restrict_sign_up_domain(event: AuthBlockingEvent) -> BeforeCreateResponse | None:
    _assert_allowed_domain(event.data.email)
    return None


# Fires on every sign-in, including returning users — covers the case
# where an account somehow already exists with a non-QIU email.
@identity_fn.before_user_signed_in()
def restrict_sign_in_domain(event: AuthBlockingEvent) -> BeforeSignInResponse | None:
    _assert_allowed_domain(event.data.email)
    return None