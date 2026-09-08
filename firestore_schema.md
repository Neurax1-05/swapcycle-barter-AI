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
| `status` | Listing status (active, matched, removed, etc.) |
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
| `status` | Match status (pending, confirmed, completed, etc.) |
| `createdAt` | Timestamp |

## Security note

Compute and validate matching logic in a trusted backend rather than trusting arbitrary client-provided match results — a client should never be able to submit its own `matches` document directly.
