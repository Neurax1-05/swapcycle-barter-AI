import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import 'main.dart' show Listing;
import 'users_service.dart';

// ============================================================
// MATCH RESULTS
// ============================================================

class MatchResultScreen extends StatelessWidget {
  const MatchResultScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser;

    if (user == null) {
      return const Scaffold(
        body: Center(child: Text('You are not logged in.')),
      );
    }

    final matchesRef = FirebaseFirestore.instance
        .collection('matches')
        .where('cycle', arrayContains: user.uid);

    return Scaffold(
      appBar: AppBar(title: const Text('My Matches')),
      body: StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
        stream: matchesRef.snapshots(),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text('Error loading matches: ${snapshot.error}'),
              ),
            );
          }

          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }

          final docs = snapshot.data!.docs;

          if (docs.isEmpty) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'No matches yet.\n\n'
                  'Submit a preference and check back '
                  'after the next matching run.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }

          return ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: docs.length,
            itemBuilder: (context, index) => MatchCard(
              key: ValueKey(docs[index].id),
              data: docs[index].data(),
            ),
          );
        },
      ),
    );
  }
}

// ------------------------------------------------------------
// One match card - resolves listings + display names once,
// not on every rebuild (the old FutureBuilder-in-itemBuilder
// pattern refetched on every frame, causing the flicker).
// ------------------------------------------------------------

class _CycleData {
  final List<Listing> listings;
  final Map<String, String> names;

  const _CycleData(this.listings, this.names);
}

class MatchCard extends StatefulWidget {
  final Map<String, dynamic> data;

  const MatchCard({super.key, required this.data});

  @override
  State<MatchCard> createState() => _MatchCardState();
}

class _MatchCardState extends State<MatchCard> {
  late final Future<_CycleData> _future;

  late final List<String> _cycle;
  late final List<String> _listingIds;

  @override
  void initState() {
    super.initState();

    _cycle = List<String>.from(widget.data['cycle'] as List? ?? []);
    _listingIds =
        List<String>.from(widget.data['listingIds'] as List? ?? []);

    _future = _load();
  }

  static String _shortId(String id) =>
      id.length <= 6 ? id : '${id.substring(0, 6)}…';

  Future<_CycleData> _load() async {
    final db = FirebaseFirestore.instance;

    final listingDocs = await Future.wait(
      _listingIds.map((id) => db.collection('listings').doc(id).get()),
    );

    final listings = listingDocs
        .where((d) => d.exists)
        .map(Listing.fromFirestore)
        .toList();

    // Reuses UsersService's cache - same source of truth as
    // AvailableItemsScreen, so names never drift between screens.
    final profiles = await Future.wait(
      _cycle.map((uid) => UsersService.fetch(uid)),
    );

    final names = <String, String>{
      for (var i = 0; i < _cycle.length; i++)
        _cycle[i]: profiles[i]?.displayName ?? _shortId(_cycle[i]),
    };

    return _CycleData(listings, names);
  }

  @override
  Widget build(BuildContext context) {
    final utility = (widget.data['totalUtility'] as num?)?.toDouble();
    final fairness = (widget.data['egalitarianScore'] as num?)?.toDouble();
    final status = widget.data['status'] as String? ?? 'pending';

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.sync_alt, color: Colors.teal),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Exchange cycle (${_cycle.length}-way)',
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                const SizedBox(width: 8),
                Chip(
                  label: Text(status),
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
              ],
            ),

            const SizedBox(height: 12),

            FutureBuilder<_CycleData>(
              future: _future,
              builder: (context, snap) {
                if (snap.hasError) {
                  return Text('Could not load trade details: ${snap.error}');
                }

                if (!snap.hasData) {
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: LinearProgressIndicator(),
                  );
                }

                final names = snap.data!.names;
                final listings = snap.data!.listings;

                String nameOf(String uid) => names[uid] ?? _shortId(uid);

                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (_cycle.isNotEmpty)
                      Text(
                        '${_cycle.map(nameOf).join(' → ')} → '
                        '${nameOf(_cycle.first)}',
                        style: const TextStyle(height: 1.4),
                      ),

                    const SizedBox(height: 8),

                    ...listings.map(
                      (l) => Padding(
                        padding: const EdgeInsets.symmetric(vertical: 2),
                        child: Text(
                          '• ${l.item} (${l.brand}) — from ${nameOf(l.owner)}',
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),

            const SizedBox(height: 12),

            if (utility != null)
              Text('Total utility: ${utility.toStringAsFixed(2)}'),

            if (fairness != null)
              Text('Fairness score: ${fairness.toStringAsFixed(2)}'),
          ],
        ),
      ),
    );
  }
}