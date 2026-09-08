# Firestore schema

users/{userId}: displayName, createdAt, rating, location

listings/{listingId}: ownerId, title, category, description, condition, status, createdAt

preferences/{preferenceId}: userId, listingId, rawText, normalized, aiModel, createdAt

matches/{matchId}: cycle[], listingIds[], totalUtility, egalitarianScore, algorithm, status, createdAt

Production note: compute/validate matching in a trusted backend rather than trusting arbitrary client-provided match results.
