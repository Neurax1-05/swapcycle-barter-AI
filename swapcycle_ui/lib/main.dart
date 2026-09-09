import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'auth_gate.dart';
import 'firebase_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  runApp(const SwapCycleApp());
}

class SwapCycleApp extends StatelessWidget {
  const SwapCycleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SwapCycle',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.teal,
        ),
        useMaterial3: true,
      ),
      home: const AuthGate(),
    );
  }
}

// ============================================================
// LISTING MODEL
// ============================================================

class Listing {
  final String id;
  final String owner;
  final String item;
  final String category;
  final String brand;
  final String condition;

  const Listing({
    required this.id,
    required this.owner,
    required this.item,
    required this.category,
    required this.brand,
    required this.condition,
  });

  factory Listing.fromFirestore(
    DocumentSnapshot<Map<String, dynamic>> doc,
  ) {
    final data = doc.data()!;

    return Listing(
      id: doc.id,
      owner: data['ownerId'] as String? ?? '',
      item: data['item'] as String? ?? '',
      category: data['category'] as String? ?? '',
      brand: data['brand'] as String? ?? '',
      condition: data['condition'] as String? ?? '',
    );
  }
}

// ============================================================
// MAIN MENU
// ============================================================

class ListingFeedScreen extends StatelessWidget {
  const ListingFeedScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('SwapCycle'),
        centerTitle: true,
        actions: [
          // MY MATCHES
          IconButton(
            icon: const Icon(Icons.sync_alt),
            tooltip: 'My Matches',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) =>
                      const MatchResultScreen(),
                ),
              );
            },
          ),

          // LOGOUT
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Sign out',
            onPressed: () {
              FirebaseAuth.instance.signOut();
            },
          ),
        ],
      ),

      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(
                Icons.swap_horiz,
                size: 90,
              ),

              const SizedBox(height: 20),

              const Text(
                'Welcome to SwapCycle',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.bold,
                ),
              ),

              const SizedBox(height: 8),

              const Text(
                'What would you like to do?',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 16,
                  color: Colors.grey,
                ),
              ),

              const SizedBox(height: 40),

              // ==================================================
              // I WANT SOMETHING
              // ==================================================

              SizedBox(
                height: 65,
                child: ElevatedButton.icon(
                  icon: const Icon(
                    Icons.search,
                    size: 28,
                  ),
                  label: const Text(
                    'I Want Something',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  onPressed: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) =>
                            const PreferenceInputScreen(),
                      ),
                    );
                  },
                ),
              ),

              const SizedBox(height: 16),

              // ==================================================
              // MAKE A LISTING
              // ==================================================

              SizedBox(
                height: 65,
                child: ElevatedButton.icon(
                  icon: const Icon(
                    Icons.add_box_outlined,
                    size: 28,
                  ),
                  label: const Text(
                    'Make a Listing',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  onPressed: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) =>
                            const AddListingScreen(),
                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ============================================================
// I WANT / PREFERENCE PAGE
// ============================================================

class PreferenceInputScreen extends StatefulWidget {
  const PreferenceInputScreen({super.key});

  @override
  State<PreferenceInputScreen> createState() =>
      _PreferenceInputScreenState();
}

class _PreferenceInputScreenState
    extends State<PreferenceInputScreen> {
  final TextEditingController _controller =
      TextEditingController();

  bool _submitting = false;
  String? _submittedText;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submitPreference() async {
    final text = _controller.text.trim();

    if (text.isEmpty) return;

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      final user =
          FirebaseAuth.instance.currentUser;

      if (user == null) {
        throw Exception('You are not logged in.');
      }

      await FirebaseFirestore.instance
          .collection('preferences')
          .add({
        'userId': user.uid,
        'rawText': text,
        'submittedAt':
            FieldValue.serverTimestamp(),
        'status': 'pending',
      });

      setState(() {
        _submittedText = text;
        _controller.clear();
      });
    } catch (e) {
      setState(() {
        _error = 'Failed to submit: $e';
      });
    } finally {
      if (mounted) {
        setState(() {
          _submitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'What are you looking for?',
        ),
      ),

      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment:
              CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Describe what you want in your own words. '
              'This gets normalized by SwapCycle\'s AI before matching.',
              style: TextStyle(
                color: Colors.grey,
              ),
            ),

            const SizedBox(height: 16),

            TextField(
              controller: _controller,
              maxLines: 4,
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                hintText:
                    'e.g. I want a beginner-friendly Yamaha guitar, '
                    'good condition is fine.',
              ),
            ),

            const SizedBox(height: 12),

            ElevatedButton(
              onPressed: _submitting
                  ? null
                  : _submitPreference,
              child: _submitting
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                      ),
                    )
                  : const Text(
                      'Submit Preference',
                    ),
            ),

            if (_error != null) ...[
              const SizedBox(height: 12),

              Text(
                _error!,
                style: const TextStyle(
                  color: Colors.red,
                ),
              ),
            ],

            if (_submittedText != null) ...[
              const SizedBox(height: 24),

              const Text(
                'Preference saved:',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                ),
              ),

              const SizedBox(height: 8),

              Card(
                color: Theme.of(context)
                    .colorScheme
                    .surfaceContainerHighest,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    _submittedText!,
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ============================================================
// MAKE A LISTING PAGE
// ============================================================

class AddListingScreen extends StatefulWidget {
  const AddListingScreen({super.key});

  @override
  State<AddListingScreen> createState() =>
      _AddListingScreenState();
}

class _AddListingScreenState
    extends State<AddListingScreen> {
  final _formKey =
      GlobalKey<FormState>();

  final _itemController =
      TextEditingController();

  final _brandController =
      TextEditingController();

  String _category = 'guitar';
  String _condition = 'good';

  bool _submitting = false;
  String? _error;
  bool _submitted = false;

  static const _categories = [
    'guitar',
    'camera',
    'bicycle',
    'book',
    'electronics',
    'clothing',
    'other',
  ];

  static const _conditions = [
    'new',
    'like new',
    'good',
    'fair',
    'poor',
  ];

  @override
  void dispose() {
    _itemController.dispose();
    _brandController.dispose();
    super.dispose();
  }

  Future<void> _submitListing() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
      _submitted = false;
    });

    try {
      final user =
          FirebaseAuth.instance.currentUser;

      if (user == null) {
        throw Exception(
          'You are not logged in.',
        );
      }

      await FirebaseFirestore.instance
          .collection('listings')
          .add({
        'ownerId': user.uid,
        'item': _itemController.text.trim(),
        'category': _category,
        'brand': _brandController.text.trim(),
        'condition': _condition,
        'status': 'active',
        'createdAt':
            FieldValue.serverTimestamp(),
      });

      setState(() {
        _submitted = true;
        _itemController.clear();
        _brandController.clear();
      });
    } catch (e) {
      setState(() {
        _error =
            'Failed to add listing: $e';
      });
    } finally {
      if (mounted) {
        setState(() {
          _submitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'Make a Listing',
        ),
      ),

      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _formKey,
          child: ListView(
            children: [
              const Text(
                'List something you own that you\'d be willing to swap.',
                style: TextStyle(
                  color: Colors.grey,
                ),
              ),

              const SizedBox(height: 16),

              // ITEM
              TextFormField(
                controller: _itemController,
                decoration:
                    const InputDecoration(
                  border:
                      OutlineInputBorder(),
                  labelText: 'Item name',
                  hintText:
                      'e.g. Acoustic Guitar',
                ),
                validator: (value) {
                  if (value == null ||
                      value.trim().isEmpty) {
                    return 'Required';
                  }

                  return null;
                },
              ),

              const SizedBox(height: 12),

              // CATEGORY
              DropdownButtonFormField<String>(
                initialValue: _category,
                decoration:
                    const InputDecoration(
                  border:
                      OutlineInputBorder(),
                  labelText: 'Category',
                ),
                items: _categories
                    .map(
                      (category) =>
                          DropdownMenuItem(
                        value: category,
                        child: Text(category),
                      ),
                    )
                    .toList(),
                onChanged: (value) {
                  if (value == null) return;

                  setState(() {
                    _category = value;
                  });
                },
              ),

              const SizedBox(height: 12),

              // BRAND
              TextFormField(
                controller:
                    _brandController,
                decoration:
                    const InputDecoration(
                  border:
                      OutlineInputBorder(),
                  labelText: 'Brand',
                  hintText:
                      'e.g. Yamaha',
                ),
                validator: (value) {
                  if (value == null ||
                      value.trim().isEmpty) {
                    return 'Required';
                  }

                  return null;
                },
              ),

              const SizedBox(height: 12),

              // CONDITION
              DropdownButtonFormField<String>(
                initialValue: _condition,
                decoration:
                    const InputDecoration(
                  border:
                      OutlineInputBorder(),
                  labelText: 'Condition',
                ),
                items: _conditions
                    .map(
                      (condition) =>
                          DropdownMenuItem(
                        value: condition,
                        child: Text(condition),
                      ),
                    )
                    .toList(),
                onChanged: (value) {
                  if (value == null) return;

                  setState(() {
                    _condition = value;
                  });
                },
              ),

              const SizedBox(height: 20),

              // SUBMIT
              ElevatedButton(
                onPressed: _submitting
                    ? null
                    : _submitListing,
                child: _submitting
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child:
                            CircularProgressIndicator(
                          strokeWidth: 2,
                        ),
                      )
                    : const Text(
                        'Add Listing',
                      ),
              ),

              if (_error != null) ...[
                const SizedBox(height: 12),

                Text(
                  _error!,
                  style:
                      const TextStyle(
                    color: Colors.red,
                  ),
                ),
              ],

              if (_submitted) ...[
                const SizedBox(height: 12),

                const Text(
                  'Listing added successfully!',
                  style: TextStyle(
                    color: Colors.green,
                    fontWeight:
                        FontWeight.bold,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

// ============================================================
// MATCH RESULTS
// ============================================================

class MatchResultScreen extends StatelessWidget {
  const MatchResultScreen({super.key});

  Future<Listing?> _fetchListing(
    String listingId,
  ) async {
    final doc = await FirebaseFirestore
        .instance
        .collection('listings')
        .doc(listingId)
        .get();

    if (!doc.exists) {
      return null;
    }

    return Listing.fromFirestore(doc);
  }

  @override
  Widget build(BuildContext context) {
    final user =
        FirebaseAuth.instance.currentUser;

    if (user == null) {
      return const Scaffold(
        body: Center(
          child: Text(
            'You are not logged in.',
          ),
        ),
      );
    }

    final uid = user.uid;

    final matchesRef =
        FirebaseFirestore.instance
            .collection('matches')
            .where(
              'cycle',
              arrayContains: uid,
            );

    return Scaffold(
      appBar: AppBar(
        title: const Text('My Matches'),
      ),

      body: StreamBuilder<
          QuerySnapshot<
              Map<String, dynamic>>>(
        stream: matchesRef.snapshots(),

        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding:
                    const EdgeInsets.all(24),
                child: Text(
                  'Error loading matches: '
                  '${snapshot.error}',
                ),
              ),
            );
          }

          if (!snapshot.hasData) {
            return const Center(
              child:
                  CircularProgressIndicator(),
            );
          }

          final docs =
              snapshot.data!.docs;

          if (docs.isEmpty) {
            return const Center(
              child: Padding(
                padding:
                    EdgeInsets.all(24),
                child: Text(
                  'No matches yet.\n\n'
                  'Submit a preference and check back '
                  'after the next matching run.',
                  textAlign:
                      TextAlign.center,
                ),
              ),
            );
          }

          return ListView.builder(
            padding:
                const EdgeInsets.all(12),
            itemCount: docs.length,

            itemBuilder:
                (context, index) {
              final data =
                  docs[index].data();

              final cycle =
                  List<String>.from(
                data['cycle']
                        as List? ??
                    [],
              );

              final listingIds =
                  List<String>.from(
                data['listingIds']
                        as List? ??
                    [],
              );

              final utility =
                  (data['totalUtility']
                          as num?)
                      ?.toDouble();

              final fairness =
                  (data['egalitarianScore']
                          as num?)
                      ?.toDouble();

              final status =
                  data['status']
                          as String? ??
                      'pending';

              return Card(
                margin:
                    const EdgeInsets.symmetric(
                  vertical: 8,
                ),

                child: Padding(
                  padding:
                      const EdgeInsets.all(16),

                  child: Column(
                    crossAxisAlignment:
                        CrossAxisAlignment
                            .start,

                    children: [
                      Row(
                        children: [
                          const Icon(
                            Icons.sync_alt,
                            color:
                                Colors.teal,
                          ),

                          const SizedBox(
                            width: 8,
                          ),

                          Text(
                            'Exchange cycle '
                            '(${cycle.length}-way)',
                            style:
                                const TextStyle(
                              fontWeight:
                                  FontWeight
                                      .bold,
                            ),
                          ),

                          const Spacer(),

                          Chip(
                            label:
                                Text(status),
                          ),
                        ],
                      ),

                      const SizedBox(
                        height: 8,
                      ),

                      if (cycle.isNotEmpty)
                        Text(
                          'Participants: '
                          '${cycle.join(' → ')} '
                          '→ ${cycle.first}',
                        ),

                      const SizedBox(
                        height: 8,
                      ),

                      ...listingIds.map(
                        (id) =>
                            FutureBuilder<
                                Listing?>(
                          future:
                              _fetchListing(
                            id,
                          ),

                          builder:
                              (context, snap) {
                            if (!snap
                                .hasData) {
                              return const Padding(
                                padding:
                                    EdgeInsets
                                        .symmetric(
                                  vertical: 4,
                                ),
                                child:
                                    LinearProgressIndicator(),
                              );
                            }

                            final listing =
                                snap.data;

                            if (listing ==
                                null) {
                              return const SizedBox
                                  .shrink();
                            }

                            return Padding(
                              padding:
                                  const EdgeInsets
                                      .symmetric(
                                vertical: 2,
                              ),
                              child: Text(
                                '• ${listing.item} '
                                '(${listing.brand}) — '
                                'from ${listing.owner}',
                              ),
                            );
                          },
                        ),
                      ),

                      const SizedBox(
                        height: 8,
                      ),

                      if (utility != null)
                        Text(
                          'Total utility: '
                          '${utility.toStringAsFixed(2)}',
                        ),

                      if (fairness != null)
                        Text(
                          'Fairness score: '
                          '${fairness.toStringAsFixed(2)}',
                        ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}