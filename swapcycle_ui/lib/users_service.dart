import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';

class UserProfile {
  final String uid;
  final String displayName;
  final String email;
  final String photoUrl;

  const UserProfile({
    required this.uid,
    required this.displayName,
    required this.email,
    required this.photoUrl,
  });

  factory UserProfile.fromFirestore(
    DocumentSnapshot<Map<String, dynamic>> doc,
  ) {
    final data = doc.data()!;
    return UserProfile(
      uid: doc.id,
      displayName: data['displayName'] as String? ?? 'Unknown',
      email: data['email'] as String? ?? '',
      photoUrl: data['photoUrl'] as String? ?? '',
    );
  }
}

class UsersService {
  static final _users = FirebaseFirestore.instance.collection('users');

  /// Call this right after a successful sign-in. Creates the user's doc
  /// on first login, refreshes name/photo on every login after (in case
  /// their Google profile changed). This IS the sign-up step — there's
  /// no separate registration form since @qiu.edu.my Google accounts
  /// are the identity source.
  static Future<void> upsertFromAuth(User user) {
    return _users.doc(user.uid).set({
      'displayName':
          user.displayName ?? user.email?.split('@').first ?? 'Unknown',
      'email': user.email ?? '',
      'photoUrl': user.photoURL ?? '',
      'lastSeen': FieldValue.serverTimestamp(),
    }, SetOptions(merge: true));
  }

  /// Simple in-memory cache so a screen with many listings doesn't
  /// re-fetch the same owner's profile once per row.
  static final Map<String, UserProfile?> _cache = {};

  static Future<UserProfile?> fetch(String uid) async {
    if (_cache.containsKey(uid)) return _cache[uid];
    final doc = await _users.doc(uid).get();
    final profile = doc.exists ? UserProfile.fromFirestore(doc) : null;
    _cache[uid] = profile;
    return profile;
  }
}
