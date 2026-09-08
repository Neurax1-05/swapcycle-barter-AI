import 'package:flutter/material.dart';

void main() {
  runApp(const SwapCycleApp());
}

class SwapCycleApp extends StatelessWidget {
  const SwapCycleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SwapCycle',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true,
      ),
      home: const ListingFeedScreen(),
    );
  }
}

class Listing {
  final String owner;
  final String item;
  final String category;
  final String brand;
  final String condition;

  const Listing({
    required this.owner,
    required this.item,
    required this.category,
    required this.brand,
    required this.condition,
  });
}

// Dummy data mirroring the users/listings model from the Python prototype
const List<Listing> dummyListings = [
  Listing(owner: 'Alice', item: 'Bike', category: 'Bicycle', brand: 'Polygon', condition: 'Good'),
  Listing(owner: 'Bob', item: 'Guitar', category: 'Guitar', brand: 'Yamaha', condition: 'Good'),
  Listing(owner: 'Charlie', item: 'Camera', category: 'Camera', brand: 'Canon', condition: 'Like New'),
  Listing(owner: 'Dina', item: 'Bike', category: 'Bicycle', brand: 'Trek', condition: 'Like New'),
  Listing(owner: 'Evan', item: 'Guitar', category: 'Guitar', brand: 'Fender', condition: 'Like New'),
  Listing(owner: 'Fiona', item: 'Camera', category: 'Camera', brand: 'Sony', condition: 'Good'),
];

class ListingFeedScreen extends StatelessWidget {
  const ListingFeedScreen({super.key});

  IconData _iconForCategory(String category) {
    switch (category.toLowerCase()) {
      case 'bicycle':
        return Icons.pedal_bike;
      case 'guitar':
        return Icons.music_note;
      case 'camera':
        return Icons.camera_alt;
      default:
        return Icons.inventory_2;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('SwapCycle'),
        centerTitle: true,
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(12),
        itemCount: dummyListings.length,
        itemBuilder: (context, index) {
          final listing = dummyListings[index];
          return Card(
            margin: const EdgeInsets.symmetric(vertical: 6),
            child: ListTile(
              leading: CircleAvatar(
                child: Icon(_iconForCategory(listing.category)),
              ),
              title: Text('${listing.item} — ${listing.brand}'),
              subtitle: Text('Owned by ${listing.owner} · ${listing.condition} condition'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const PreferenceInputScreen(),
                  ),
                );
              },
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (context) => const PreferenceInputScreen(),
            ),
          );
        },
        icon: const Icon(Icons.add),
        label: const Text('Request Swap'),
      ),
    );
  }
}

class PreferenceInputScreen extends StatefulWidget {
  const PreferenceInputScreen({super.key});

  @override
  State<PreferenceInputScreen> createState() => _PreferenceInputScreenState();
}

class _PreferenceInputScreenState extends State<PreferenceInputScreen> {
  final TextEditingController _controller = TextEditingController();
  String? _submittedText;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('What are you looking for?')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Describe what you want in your own words. '
              'This gets normalized by SwapCycle\'s AI before matching.',
              style: TextStyle(color: Colors.grey),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              maxLines: 3,
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                hintText: 'e.g. I want a beginner-friendly Yamaha guitar, good condition is fine.',
              ),
            ),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: () {
                setState(() {
                  _submittedText = _controller.text;
                });
              },
              child: const Text('Submit Preference'),
            ),
            if (_submittedText != null && _submittedText!.isNotEmpty) ...[
              const SizedBox(height: 24),
              const Text('Submitted (not yet sent to AI/backend):',
                  style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Card(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(_submittedText!),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}