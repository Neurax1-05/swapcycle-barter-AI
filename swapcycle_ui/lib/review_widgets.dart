import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';

import 'users_service.dart';

/// Read-only row of 5 stars (supports half stars for averages).
class StarRow extends StatelessWidget {
  final double rating;
  final double size;

  const StarRow({super.key, required this.rating, this.size = 18});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: List.generate(5, (i) {
        final v = rating - i;
        final icon = v >= 0.75
            ? Icons.star
            : v >= 0.25
                ? Icons.star_half
                : Icons.star_border;
        return Icon(icon, size: size, color: Colors.amber);
      }),
    );
  }
}

/// Average rating + testimonials for one user, read from `reviews`.
///
/// reviews/{matchId}_{reviewerUid}:
///   matchId, reviewerId, revieweeId, rating (1-5), comment, createdAt
///
/// The average is computed here in the app (no Cloud Function needed).
/// Sorting is done client-side so no composite Firestore index is required.
class ReviewsSection extends StatelessWidget {
  final String uid;

  const ReviewsSection({super.key, required this.uid});

  static DateTime _when(Map<String, dynamic> m) {
    final t = m['createdAt'];
    // A just-written review has no server timestamp yet: treat as newest.
    return t is Timestamp ? t.toDate() : DateTime.now();
  }

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
      stream: FirebaseFirestore.instance
          .collection('reviews')
          .where('revieweeId', isEqualTo: uid)
          .snapshots(),
      builder: (context, snap) {
        if (snap.hasError) {
          return Text(
            'ERROR loading reviews:\n${snap.error}',
            style: const TextStyle(color: Colors.red),
          );
        }
        if (!snap.hasData) {
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: LinearProgressIndicator(),
          );
        }

        final docs = snap.data!.docs.toList()
          ..sort((a, b) => _when(b.data()).compareTo(_when(a.data())));

        if (docs.isEmpty) {
          return const Text(
            'No reviews yet.',
            style: TextStyle(color: Colors.grey),
          );
        }

        final ratings = docs
            .map((d) => (d.data()['rating'] as num?)?.toDouble() ?? 0)
            .toList();
        final average = ratings.reduce((a, b) => a + b) / ratings.length;

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  average.toStringAsFixed(1),
                  style: const TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 10),
                StarRow(rating: average, size: 22),
                const SizedBox(width: 10),
                Text(
                  '(${docs.length} ${docs.length == 1 ? 'review' : 'reviews'})',
                  style: const TextStyle(color: Colors.grey),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ...docs.take(20).map(
                  (d) => _ReviewTile(key: ValueKey(d.id), data: d.data()),
                ),
          ],
        );
      },
    );
  }
}

class _ReviewTile extends StatefulWidget {
  final Map<String, dynamic> data;

  const _ReviewTile({super.key, required this.data});

  @override
  State<_ReviewTile> createState() => _ReviewTileState();
}

class _ReviewTileState extends State<_ReviewTile> {
  late final Future<UserProfile?> _reviewer;

  @override
  void initState() {
    super.initState();
    _reviewer =
        UsersService.fetch(widget.data['reviewerId'] as String? ?? '');
  }

  @override
  Widget build(BuildContext context) {
    final rating = (widget.data['rating'] as num?)?.toDouble() ?? 0;
    final comment = (widget.data['comment'] as String?)?.trim() ?? '';

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: FutureBuilder<UserProfile?>(
                    future: _reviewer,
                    builder: (context, snap) => Text(
                      snap.data?.displayName ?? 'A QIU student',
                      style: const TextStyle(fontWeight: FontWeight.w600),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ),
                StarRow(rating: rating, size: 16),
              ],
            ),
            if (comment.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(comment),
            ],
          ],
        ),
      ),
    );
  }
}
