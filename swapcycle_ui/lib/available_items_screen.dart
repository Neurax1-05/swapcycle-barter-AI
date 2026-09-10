import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import 'main.dart'; // Listing model
import 'users_service.dart';

class AvailableItemsScreen extends StatelessWidget {
  const AvailableItemsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final uid = FirebaseAuth.instance.currentUser?.uid;

    final listingsRef = FirebaseFirestore.instance
        .collection('listings')
        .where('status', isEqualTo: 'active')
        .snapshots();

    return Scaffold(
      appBar: AppBar(title: const Text('Available Items')),
      body: StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
        stream: listingsRef,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Text(
                  'ERROR loading items:\n${snapshot.error}',
                  style: const TextStyle(color: Colors.red),
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }

          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }

          final docs = snapshot.data!.docs
              .where((d) => (d.data()['ownerId'] as String?) != uid)
              .toList(); // hide your own listings

          if (docs.isEmpty) {
            return const Center(child: Text('No items available right now.'));
          }

          return ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: docs.length,
            itemBuilder: (context, index) {
              final listing = Listing.fromFirestore(docs[index]);

              return Card(
                margin: const EdgeInsets.symmetric(vertical: 6),
                child: FutureBuilder<UserProfile?>(
                  future: UsersService.fetch(listing.ownerId),
                  builder: (context, snap) {
                    if (snap.hasError) {
                      debugPrint('Failed to load owner profile: ${snap.error}');
                    }

                    final photo = snap.data?.photoUrl ?? '';
                    final name = snap.data?.displayName ?? 'Unknown user';

                    return ListTile(
                      leading: CircleAvatar(
                        backgroundImage:
                            photo.isNotEmpty ? NetworkImage(photo) : null,
                        onBackgroundImageError: photo.isNotEmpty
                            ? (exception, stackTrace) {
                                debugPrint('Failed to load avatar: $exception');
                              }
                            : null,
                        child: photo.isEmpty
                            ? const Icon(Icons.person)
                            : null,
                      ),
                      title: Text(listing.item),
                      subtitle: Text(
                        '${listing.brand} • ${listing.condition} — listed by $name',
                      ),
                    );
                  },
                ),
              );
            },
          );
        },
      ),
    );
  }
}