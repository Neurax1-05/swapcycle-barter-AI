import 'dart:convert';
import 'dart:typed_data';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

/// Max size of a compressed photo stored inline in a Firestore document.
/// (A Firestore document is capped at 1 MiB and base64 adds ~33%.)
const int _kMaxImageBytes = 600 * 1024;

/// Private 1-to-1 chat between two adjacent users in a matched cycle.
///
/// Firestore path:
///   matches/{matchId}/chats/{chatId}/messages/{id}
///
/// Every message has: type, senderId, senderName, createdAt, plus:
///   type 'text'     -> text
///   type 'image'    -> imageBase64 (compressed JPEG)
///   type 'location' -> lat, lng (snapshot of the sender's position)
///
/// chatId = the two uids sorted and joined with '_' (same id for both users).
class ChatScreen extends StatefulWidget {
  final String matchId;
  final String otherUid;
  final String otherName;

  const ChatScreen({
    super.key,
    required this.matchId,
    required this.otherUid,
    required this.otherName,
  });

  static String chatIdFor(String a, String b) =>
      ([a, b]..sort()).join('_');

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _controller = TextEditingController();
  final User _user = FirebaseAuth.instance.currentUser!;
  bool _busy = false;

  late final CollectionReference<Map<String, dynamic>> _messages;
  late final Stream<QuerySnapshot<Map<String, dynamic>>> _stream;

  @override
  void initState() {
    super.initState();
    final chatId = ChatScreen.chatIdFor(_user.uid, widget.otherUid);
    _messages = FirebaseFirestore.instance
        .collection('matches')
        .doc(widget.matchId)
        .collection('chats')
        .doc(chatId)
        .collection('messages');
    // Newest first; the list below is reversed so new messages sit at the bottom.
    _stream = _messages.orderBy('createdAt', descending: true).snapshots();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  /// Runs a send action with a busy flag and a single error handler.
  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      _snack('Could not send: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _post(Map<String, dynamic> payload) {
    return _messages.add({
      'senderId': _user.uid,
      'senderName': _user.displayName ?? 'Someone',
      'createdAt': FieldValue.serverTimestamp(),
      ...payload,
    });
  }

  // ---------------------------------------------------------------- text

  Future<void> _sendText() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    await _run(() async {
      await _post({'type': 'text', 'text': text});
      _controller.clear();
    });
  }

  // --------------------------------------------------------------- photo

  Future<void> _sendImage(ImageSource source) async {
    final picked = await ImagePicker().pickImage(
      source: source,
      maxWidth: 1024,
      maxHeight: 1024,
      imageQuality: 60,
    );
    if (picked == null) return;
    final bytes = await picked.readAsBytes();
    if (bytes.length > _kMaxImageBytes) {
      _snack('That photo is too large. Try a smaller one.');
      return;
    }
    await _run(() => _post({
          'type': 'image',
          'imageBase64': base64Encode(bytes),
        }));
  }

  // ------------------------------------------------------------ location

  Future<void> _shareLocation() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Share your location?'),
        content: Text(
          'This sends your current position to ${widget.otherName} '
          'so you can meet up. It is a one-time snapshot, not live tracking.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Share'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    await _run(() async {
      if (!await Geolocator.isLocationServiceEnabled()) {
        _snack('Turn on location services first.');
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        _snack('Location permission is needed to share your location.');
        return;
      }
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15),
        ),
      );
      await _post({
        'type': 'location',
        'lat': pos.latitude,
        'lng': pos.longitude,
      });
    });
  }

  // ------------------------------------------------------------ attach UI

  void _openAttachSheet() {
    showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Photo from gallery'),
              onTap: () {
                Navigator.pop(ctx);
                _sendImage(ImageSource.gallery);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Take a photo'),
              onTap: () {
                Navigator.pop(ctx);
                _sendImage(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.location_on_outlined),
              title: const Text('Share my location'),
              onTap: () {
                Navigator.pop(ctx);
                _shareLocation();
              },
            ),
          ],
        ),
      ),
    );
  }

  // --------------------------------------------------------------- build

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.otherName)),
      body: Column(
        children: [
          Expanded(
            child: StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
              stream: _stream,
              builder: (context, snap) {
                if (snap.hasError) {
                  return Center(child: Text('Error: ${snap.error}'));
                }
                if (!snap.hasData) {
                  return const Center(child: CircularProgressIndicator());
                }
                final docs = snap.data!.docs;
                if (docs.isEmpty) {
                  return Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        'No messages yet. Say hi to ${widget.otherName} '
                        'and agree on when and where to swap.',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  );
                }
                return ListView.builder(
                  reverse: true,
                  padding: const EdgeInsets.all(12),
                  itemCount: docs.length,
                  itemBuilder: (context, i) {
                    final m = docs[i].data();
                    return _MessageBubble(
                      key: ValueKey(docs[i].id),
                      m: m,
                      mine: m['senderId'] == _user.uid,
                    );
                  },
                );
              },
            ),
          ),
          if (_busy) const LinearProgressIndicator(minHeight: 2),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(4, 4, 12, 8),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.add_circle_outline),
                    tooltip: 'Attach',
                    onPressed: _busy ? null : _openAttachSheet,
                  ),
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _sendText(),
                      decoration: const InputDecoration(
                        border: OutlineInputBorder(),
                        hintText: 'Message',
                        isDense: true,
                      ),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.send),
                    onPressed: _busy ? null : _sendText,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ====================================================================
// Message bubble
// ====================================================================

class _MessageBubble extends StatelessWidget {
  final Map<String, dynamic> m;
  final bool mine;

  const _MessageBubble({super.key, required this.m, required this.mine});

  static String _time(dynamic ts) {
    if (ts is! Timestamp) return '';
    final d = ts.toDate();
    return '${d.hour.toString().padLeft(2, '0')}:'
        '${d.minute.toString().padLeft(2, '0')}';
  }

  Widget _body(String type) {
    switch (type) {
      case 'image':
        return _Base64Image(data: m['imageBase64'] as String? ?? '');
      case 'location':
        return _LocationCard(
          lat: (m['lat'] as num).toDouble(),
          lng: (m['lng'] as num).toDouble(),
        );
      default:
        return Text(m['text'] as String? ?? '');
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final type = m['type'] as String? ?? 'text';
    final media = type == 'image';

    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: EdgeInsets.all(media ? 4 : 10),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.78,
        ),
        decoration: BoxDecoration(
          color: mine ? scheme.primaryContainer : scheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment:
              mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            _body(type),
            const SizedBox(height: 2),
            Text(
              _time(m['createdAt']),
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      ),
    );
  }
}

// ====================================================================
// Photo bubble (base64 stored in Firestore)
// ====================================================================

class _Base64Image extends StatefulWidget {
  final String data;
  const _Base64Image({required this.data});

  @override
  State<_Base64Image> createState() => _Base64ImageState();
}

class _Base64ImageState extends State<_Base64Image> {
  Uint8List? _bytes;

  @override
  void initState() {
    super.initState();
    try {
      _bytes = base64Decode(widget.data);
    } catch (_) {
      _bytes = null;
    }
  }

  void _openFullscreen() {
    final bytes = _bytes;
    if (bytes == null) return;
    showDialog<void>(
      context: context,
      builder: (ctx) => Dialog.fullscreen(
        backgroundColor: Colors.black,
        child: Stack(
          children: [
            Center(child: InteractiveViewer(child: Image.memory(bytes))),
            Positioned(
              top: 8,
              right: 8,
              child: SafeArea(
                child: IconButton(
                  icon: const Icon(Icons.close, color: Colors.white),
                  onPressed: () => Navigator.pop(ctx),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bytes = _bytes;
    if (bytes == null) {
      return const Padding(
        padding: EdgeInsets.all(8),
        child: Text('Photo unavailable'),
      );
    }
    return GestureDetector(
      onTap: _openFullscreen,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 280),
          child: Image.memory(
            bytes,
            width: 220,
            fit: BoxFit.cover,
            gaplessPlayback: true,
          ),
        ),
      ),
    );
  }
}

// ====================================================================
// Location bubble
// ====================================================================

class _LocationCard extends StatelessWidget {
  final double lat;
  final double lng;
  const _LocationCard({required this.lat, required this.lng});

  Future<void> _open(BuildContext context) async {
    final uri = Uri.parse(
      'https://www.google.com/maps/search/?api=1&query=$lat,$lng',
    );
    final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!launched && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open Maps.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 220,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.location_on, size: 20),
              SizedBox(width: 6),
              Text('Shared location',
                  style: TextStyle(fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: 4),
          Text('${lat.toStringAsFixed(5)}, ${lng.toStringAsFixed(5)}'),
          const SizedBox(height: 8),
          FilledButton.tonalIcon(
            onPressed: () => _open(context),
            icon: const Icon(Icons.map_outlined),
            label: const Text('Open in Maps'),
          ),
        ],
      ),
    );
  }
}
