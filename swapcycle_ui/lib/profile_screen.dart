import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import 'main.dart'; // Listing model
import 'users_service.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser;

    if (user == null) {
      return const Scaffold(body: Center(child: Text('Not logged in.')));
    }

    return Scaffold(
      appBar: AppBar(title: const Text('My Profile')),
      body: FutureBuilder<UserProfile?>(
        future: UsersService.fetch(user.uid),
        builder: (context, snapshot) {
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }

          final profile = snapshot.data;
          final name = profile?.displayName ?? user.displayName ?? 'Unknown';
          final email = profile?.email ?? user.email ?? '';
          final photoUrl = profile?.photoUrl ?? user.photoURL ?? '';

          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Center(
                child: Column(
                  children: [
                    CircleAvatar(
                      radius: 44,
                      backgroundImage:
                          photoUrl.isNotEmpty ? NetworkImage(photoUrl) : null,
                      child: photoUrl.isEmpty
                          ? const Icon(Icons.person, size: 44)
                          : null,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      name,
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(email, style: const TextStyle(color: Colors.grey)),
                  ],
                ),
              ),
              const SizedBox(height: 28),
              const Text(
                'My Listings',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
                stream: FirebaseFirestore.instance
                    .collection('listings')
                    .where('ownerId', isEqualTo: user.uid)
                    .snapshots(),
                builder: (context, snap) {
                  if (!snap.hasData) {
                    return const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: LinearProgressIndicator(),
                    );
                  }

                  final docs = snap.data!.docs;

                  if (docs.isEmpty) {
                    return const Text(
                      "You haven't listed anything yet.",
                      style: TextStyle(color: Colors.grey),
                    );
                  }

                  return Column(
                    children: docs.map((doc) {
                      final listing = Listing.fromFirestore(doc);
                      return Card(
                        child: ListTile(
                          title: Text(listing.item),
                          subtitle: Text(
                            '${listing.brand} • ${listing.condition} • ${listing.category}',
                          ),
                        ),
                      );
                    }).toList(),
                  );
                },
              ),
            ],
          );
        },
      ),
    );
  }
}
