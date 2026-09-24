import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import 'chat_screen.dart';
import 'main.dart' show Listing;
import 'profile_screen.dart';
import 'review_widgets.dart';
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
              matchId: docs[index].id,
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
  final String matchId;
  final Map<String, dynamic> data;

  const MatchCard({super.key, required this.matchId, required this.data});

  @override
  State<MatchCard> createState() => _MatchCardState();
}

class _MatchCardState extends State<MatchCard> {
  late final Future<_CycleData> _future;

  late final List<String> _cycle;
  late final List<String> _listingIds;
  late final String _myUid;

  // Filled in once _load() finishes, so the footer (receipt / rating
  // section) can show names too.
  Map<String, String> _names = const {};

  @override
  void initState() {
    super.initState();

    _myUid = FirebaseAuth.instance.currentUser!.uid;
    _cycle = List<String>.from(widget.data['cycle'] as List? ?? []);
    _listingIds =
        List<String>.from(widget.data['listingIds'] as List? ?? []);

    _future = _load();
  }

  static String _shortId(String id) =>
      id.length <= 6 ? id : '${id.substring(0, 6)}…';

  String _nameOf(String uid) => _names[uid] ?? _shortId(uid);

  /// The people I actually swap with: the one before me and the one
  /// after me in the cycle. In a 2-way swap they are the same person.
  List<String> get _neighbours {
    final n = _cycle.length;
    final i = _cycle.indexOf(_myUid);
    if (n < 2 || i < 0) return const [];
    return {_cycle[(i + 1) % n], _cycle[(i - 1 + n) % n]}.toList();
  }

  /// exchanges[] follows the matching graph: fromUser is the BUYER (the one
  /// who wants the item) and toUser is the SELLER (the owner of `item`).
  /// So the record where fromUser == me tells me which item I receive and
  /// who gives it to me.
  Map<dynamic, dynamic>? get _myExchange {
    final exchanges = widget.data['exchanges'] as List? ?? const [];
    for (final e in exchanges) {
      if (e is Map && e['fromUser'] == _myUid) return e;
    }
    return null;
  }

  /// The person who gives ME my item.
  String? get _giverUid {
    final toUser = _myExchange?['toUser'];
    if (toUser is String && toUser.isNotEmpty) return toUser;

    // Fallback if exchanges[] is missing: cycle edges point buyer -> seller,
    // so the person who gives me my item is the next one in the cycle.
    final n = _cycle.length;
    final i = _cycle.indexOf(_myUid);
    if (n < 2 || i < 0) return null;
    return _cycle[(i + 1) % n];
  }

  /// Name of the item I am supposed to receive.
  String? get _receivedItem => _myExchange?['item'] as String?;

  DocumentReference<Map<String, dynamic>> get _matchRef =>
      FirebaseFirestore.instance.collection('matches').doc(widget.matchId);

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

    if (mounted) setState(() => _names = names);

    return _CycleData(listings, names);
  }

  // Cycle-wide, all-or-nothing: status flips to 'confirmed' only when
  // every user in the cycle has confirmed.
  Future<void> _confirm() async {
    try {
      await FirebaseFirestore.instance.runTransaction((tx) async {
        final snap = await tx.get(_matchRef);
        final data = snap.data()!;
        final cycle = List<String>.from(data['cycle'] ?? []);
        final conf = Map<String, dynamic>.from(data['confirmations'] ?? {});
        conf[_myUid] = true;
        final everyoneIn = cycle.every((u) => conf[u] == true);
        tx.update(_matchRef, {
          'confirmations.$_myUid': true,
          if (everyoneIn) 'status': 'confirmed',
        });
      });
    } catch (e) {
      _snack('Could not confirm: $e');
    }
  }

  Future<void> _decline() async {
    try {
      await _matchRef.update({'status': 'declined'});
    } catch (e) {
      _snack('Could not decline: $e');
    }
  }

  // "I received my item": same all-or-nothing idea. The match becomes
  // 'completed' once every person in the cycle has marked receipt.
  Future<void> _markReceived() async {
    final giver = _giverUid;
    final item = _receivedItem ?? 'your item';
    final from = giver == null ? 'your swap partner' : _nameOf(giver);

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Confirm receipt'),
        content: Text('Did you receive $item from $from? '
            'This can\'t be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Not yet'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Yes, I received it'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    try {
      await FirebaseFirestore.instance.runTransaction((tx) async {
        final snap = await tx.get(_matchRef);
        final data = snap.data()!;
        final cycle = List<String>.from(data['cycle'] ?? []);
        final rec = Map<String, dynamic>.from(data['receipts'] ?? {});
        rec[_myUid] = true;
        final everyoneIn = cycle.every((u) => rec[u] == true);
        tx.update(_matchRef, {
          'receipts.$_myUid': true,
          if (everyoneIn) 'status': 'completed',
        });
      });
    } catch (e) {
      _snack('Could not save: $e');
    }
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    final utility = (widget.data['totalUtility'] as num?)?.toDouble();
    final fairness = (widget.data['egalitarianScore'] as num?)?.toDouble();
    final status = widget.data['status'] as String? ?? 'pending';

    final conf =
        Map<String, dynamic>.from(widget.data['confirmations'] as Map? ?? {});
    final confirmedCount = _cycle.where((u) => conf[u] == true).length;
    final iConfirmed = conf[_myUid] == true;

    final receipts =
        Map<String, dynamic>.from(widget.data['receipts'] as Map? ?? {});
    final receivedCount = _cycle.where((u) => receipts[u] == true).length;
    final iReceived = receipts[_myUid] == true;

    // AI explanation written by the matching bridge (advisory only).
    final aiRaw = widget.data['aiEvaluation'];
    final ai = aiRaw is Map ? Map<String, dynamic>.from(aiRaw) : null;
    final aiReason = (ai?['reason'] as String?)?.trim();
    final aiFactors = ((ai?['qualitative_factors_considered'] as List?) ??
            const [])
        .map((e) => e.toString())
        .toList();
    final aiAdjustment = (ai?['suggested_adjustment'] as String?)?.trim();

    final giver = _giverUid;

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

                    const SizedBox(height: 12),

                    // Private chat + profile only for the people I swap with.
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: _neighbours
                          .map(
                            (uid) => Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                OutlinedButton.icon(
                                  icon: const Icon(
                                      Icons.chat_bubble_outline),
                                  label: Text('Chat with ${nameOf(uid)}'),
                                  onPressed: () => Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                      builder: (_) => ChatScreen(
                                        matchId: widget.matchId,
                                        otherUid: uid,
                                        otherName: nameOf(uid),
                                      ),
                                    ),
                                  ),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.person_outline),
                                  tooltip: "${nameOf(uid)}'s profile",
                                  onPressed: () => Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                      builder: (_) =>
                                          ProfileScreen(uid: uid),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          )
                          .toList(),
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

            if (aiReason != null && aiReason.isNotEmpty)
              _AiWhyCard(
                reason: aiReason,
                factors: aiFactors,
                adjustment: aiAdjustment,
              ),

            const Divider(height: 24),

            if (status == 'completed') ...[
              const Text(
                'Trade completed. Thanks for swapping!',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              if (giver != null) ...[
                const SizedBox(height: 8),
                _ReviewSection(
                  matchId: widget.matchId,
                  myUid: _myUid,
                  giverUid: giver,
                  giverName: _nameOf(giver),
                ),
              ],
            ] else if (status == 'confirmed') ...[
              const Text(
                'Everyone confirmed. Arrange your swaps in chat.',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '$receivedCount of ${_cycle.length} received',
                    ),
                  ),
                  ElevatedButton(
                    onPressed: iReceived ? null : _markReceived,
                    child: Text(iReceived ? 'Received' : 'I received my item'),
                  ),
                ],
              ),
            ] else if (status == 'declined')
              const Text('This trade was declined.')
            else
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '$confirmedCount of ${_cycle.length} confirmed',
                    ),
                  ),
                  TextButton(
                    onPressed: _decline,
                    child: const Text('Decline'),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    onPressed: iConfirmed ? null : _confirm,
                    child: Text(iConfirmed ? 'Confirmed' : 'Confirm'),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

// ------------------------------------------------------------
// "Why this match" - AI explanation (advisory, never changes a match)
// ------------------------------------------------------------

class _AiWhyCard extends StatelessWidget {
  final String reason;
  final List<String> factors;
  final String? adjustment;

  const _AiWhyCard({
    required this.reason,
    required this.factors,
    this.adjustment,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: scheme.secondaryContainer,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.auto_awesome,
                  size: 18, color: scheme.onSecondaryContainer),
              const SizedBox(width: 6),
              Text(
                'Why this match',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  color: scheme.onSecondaryContainer,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(reason, style: TextStyle(color: scheme.onSecondaryContainer)),
          if (factors.isNotEmpty) ...[
            const SizedBox(height: 6),
            ...factors.map(
              (f) => Text(
                '• $f',
                style: TextStyle(
                  fontSize: 12,
                  color: scheme.onSecondaryContainer,
                ),
              ),
            ),
          ],
          if (adjustment != null && adjustment!.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              'Suggestion: $adjustment',
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: scheme.onSecondaryContainer,
              ),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            'AI suggestion only. The match is built by the BGCC matching '
            'algorithm and nothing happens until every person confirms.',
            style: TextStyle(
              fontSize: 11,
              fontStyle: FontStyle.italic,
              color: scheme.onSecondaryContainer,
            ),
          ),
        ],
      ),
    );
  }
}

// ------------------------------------------------------------
// Rating + testimonial for the person who gave me my item
// ------------------------------------------------------------

class _ReviewInput {
  final int rating;
  final String comment;

  const _ReviewInput(this.rating, this.comment);
}

class _ReviewSection extends StatelessWidget {
  final String matchId;
  final String myUid;
  final String giverUid;
  final String giverName;

  const _ReviewSection({
    required this.matchId,
    required this.myUid,
    required this.giverUid,
    required this.giverName,
  });

  // One review per match per reviewer (the rules enforce this id format).
  String get _reviewId => '${matchId}_$myUid';

  Future<void> _rate(BuildContext context) async {
    final input = await showDialog<_ReviewInput>(
      context: context,
      builder: (_) => _RatingDialog(name: giverName),
    );
    if (input == null) return;

    try {
      await FirebaseFirestore.instance
          .collection('reviews')
          .doc(_reviewId)
          .set({
        'matchId': matchId,
        'reviewerId': myUid,
        'revieweeId': giverUid,
        'rating': input.rating,
        'comment': input.comment,
        'createdAt': FieldValue.serverTimestamp(),
      });
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not save your review: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
      stream: FirebaseFirestore.instance
          .collection('reviews')
          .doc(_reviewId)
          .snapshots(),
      builder: (context, snap) {
        if (snap.hasError) {
          return Text('Could not load your review: ${snap.error}');
        }
        if (!snap.hasData) return const SizedBox.shrink();

        final doc = snap.data!;
        if (doc.exists) {
          final rating = (doc.data()?['rating'] as num?)?.toDouble() ?? 0;
          return Row(
            children: [
              Text('You rated $giverName  '),
              StarRow(rating: rating, size: 18),
            ],
          );
        }

        return Row(
          children: [
            Expanded(child: Text('How was your swap with $giverName?')),
            FilledButton(
              onPressed: () => _rate(context),
              child: const Text('Rate'),
            ),
          ],
        );
      },
    );
  }
}

class _RatingDialog extends StatefulWidget {
  final String name;

  const _RatingDialog({required this.name});

  @override
  State<_RatingDialog> createState() => _RatingDialogState();
}

class _RatingDialogState extends State<_RatingDialog> {
  int _rating = 0;
  final _comment = TextEditingController();

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Rate ${widget.name}'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Wrap(
            alignment: WrapAlignment.center,
            children: List.generate(5, (i) {
              return IconButton(
                visualDensity: VisualDensity.compact,
                icon: Icon(
                  i < _rating ? Icons.star : Icons.star_border,
                  color: Colors.amber,
                  size: 32,
                ),
                onPressed: () => setState(() => _rating = i + 1),
              );
            }),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _comment,
            maxLength: 300,
            maxLines: 3,
            decoration: const InputDecoration(
              hintText: 'Leave a testimonial (optional)',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _rating == 0
              ? null
              : () => Navigator.pop(
                    context,
                    _ReviewInput(_rating, _comment.text.trim()),
                  ),
          child: const Text('Submit'),
        ),
      ],
    );
  }
}
