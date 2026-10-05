# Firestore Schema

## `users/{userId}`
| Field | Description |
|---|---|
| `displayName` | User's display name |
| `createdAt` | Account creation timestamp |
| `rating` | User's trust/rating score |
| `location` | User's location |

## `listings/{listingId}`
| Field | Description |
|---|---|
| `ownerId` | UID of the listing owner |
| `title` | Listing title |
| `category` | Item category (guitar, camera, bicycle, etc.) |
| `description` | Free-text description |
| `condition` | Item condition (fair / good / like_new / new) |
| `status` | `active` (set by the app) → `in_trade` while in a pending/confirmed match → `traded` once the match completes. The backend sets the last two; owners can only edit or delete an `active` listing. A declined or expired match puts the listing back to `active`. |
| `createdAt` | Listing creation timestamp |

## `preferences/{preferenceId}`
| Field | Description |
|---|---|
| `userId` | UID of the user who made the request |
| `listingId` | Associated listing, if applicable |
| `rawText` | Original natural-language preference text |
| `normalized` | AI-normalized structured preference object |
| `aiModel` | Model used for normalization |
| `createdAt` | Timestamp |

## `matches/{matchId}`
| Field | Description |
|---|---|
| `cycle[]` | Ordered list of user IDs in the exchange cycle |
| `listingIds[]` | Listings involved in the exchange |
| `totalUtility` | Sum of utility scores across the cycle |
| `egalitarianScore` | Fairness score (min utility across participants) |
| `algorithm` | Matching algorithm used (e.g. BGCC) |
| `status` | `pending` → `confirmed` → `completed`; or `declined` (a member said no) or `expired` (set by the backend) |
| `createdAt` | Timestamp |
| `expiresAt` | Deadline for a `pending` match (`MATCH_TTL_HOURS`, default 72). Past it, clients can no longer confirm or decline, and the backend sets `expired`, freeing everyone for the next run |

## `users/{uid}`
| Field | Description |
|---|---|
| `displayName`, `photoUrl`, `lastSeen` | Public profile, read one document at a time by any QIU user (listing the collection is denied) |
| `consentVersion`, `consentAcceptedAt` | Consent choice |

The email is not stored here. Matches are readable only by the users in `cycle`.

## Security note

Compute and validate matching logic in a trusted backend rather than trusting arbitrary client-provided match results — a client should never be able to submit its own `matches` document directly.
