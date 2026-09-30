"""SwapCycle Cloud Functions.

1. Domain lock (Auth blocking functions): only @qiu.edu.my accounts may
   sign up or sign in. Needs Identity Platform enabled on the project.
2. Matching trigger: when a new preference document is created, run the
   same matching pipeline as `python firestore_bridge.py`
   (Gemini #1 normalisation -> BGCC -> Gemini #2 arbitration -> matches).

The engine modules (firestore_bridge.py, bgcc_prototype.py, ...) are copies
kept in this folder by `python sync_functions.py`, because `firebase deploy`
only uploads the functions/ folder.
"""

import traceback

import firebase_admin
from firebase_admin import firestore
from firebase_functions import firestore_fn, identity_fn, options
from firebase_functions.https_fn import HttpsError
from firebase_functions.identity_fn import (
    AuthBlockingEvent,
    BeforeCreateResponse,
    BeforeSignInResponse,
)

firebase_admin.initialize_app()

ALLOWED_DOMAIN = "qiu.edu.my"


# ------------------------------------------------------------------
# 1. Domain lock
# ------------------------------------------------------------------

def _assert_allowed_domain(email: str | None) -> None:
    if not email or not email.lower().endswith(f"@{ALLOWED_DOMAIN}"):
        # Raising here blocks the sign-up/sign-in entirely, before any
        # user record is created. This is the real enforcement boundary --
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


# Fires on every sign-in, including returning users -- covers the case
# where an account somehow already exists with a non-QIU email.
@identity_fn.before_user_signed_in()
def restrict_sign_in_domain(event: AuthBlockingEvent) -> BeforeSignInResponse | None:
    _assert_allowed_domain(event.data.email)
    return None


# ------------------------------------------------------------------
# 2. Matching trigger
# ------------------------------------------------------------------

# Trigger on CREATE only, never on write: the pipeline itself updates
# preference documents (pending -> processed), and a write trigger would
# fire again on its own updates. Clients cannot edit preferences (see
# firestore.rules), so "created" covers every new request.
#
# max_instances=1 keeps runs one at a time, so two preferences created
# together cannot produce overlapping matching runs.
@firestore_fn.on_document_created(
    document="preferences/{prefId}",
    region="asia-southeast1",  # same region as the Firestore database
    secrets=["OPENROUTER_API_KEY"],
    timeout_sec=300,
    memory=options.MemoryOption.MB_512,
    max_instances=1,
)
def run_matching_on_preference_create(
    event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None],
) -> None:
    pref_id = event.params.get("prefId")
    print(f"New preference {pref_id}: running matching pipeline")

    try:
        # Imported here so a problem in the engine shows up in this
        # function's logs instead of breaking every function at load time.
        import firestore_bridge

        summary = firestore_bridge.run_matching(firestore.client())
        print(f"Matching finished: {summary}")

    except Exception:
        print("Matching run failed:")
        print(traceback.format_exc())
        raise
