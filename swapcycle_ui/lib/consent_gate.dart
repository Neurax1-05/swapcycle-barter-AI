import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:google_sign_in/google_sign_in.dart';

/// Bump this number whenever the text below changes and everyone will be
/// asked to agree again on their next login.
const int kConsentVersion = 1;

/// Meetup safety guidance (checklist: "no payment/escrow in the app").
const List<String> kSafetyTips = [
  'Meet in a public, well-lit place on campus, ideally during the day.',
  'Tell a friend where you are going and who you are meeting.',
  'Check the item before you hand yours over. If it is not as described, '
      'you can walk away.',
  'Never send money, deposits or bank details. SwapCycle handles no '
      'payments, so nobody has a reason to ask for them.',
  'Only share your location with the people in your swap, and only when '
      'you are ready to meet.',
  'If anything feels wrong, stop the swap and decline it in the app.',
];

/// A reusable "Meetup safety tips" bottom sheet (used from the chat screen).
void showSafetyTips(BuildContext context) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 20, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Meetup safety tips',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            ...kSafetyTips.map(
              (t) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('•  '),
                    Expanded(child: Text(t)),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

/// Shows a one-time consent screen after login. Once the person agrees, the
/// choice is stored on their user document (consentVersion +
/// consentAcceptedAt) and this widget just shows [child] from then on.
class ConsentGate extends StatefulWidget {
  final Widget child;

  const ConsentGate({super.key, required this.child});

  @override
  State<ConsentGate> createState() => _ConsentGateState();
}

class _ConsentGateState extends State<ConsentGate> {
  late Future<bool> _accepted;
  bool _agreed = false;
  bool _saving = false;
  String? _error;

  DocumentReference<Map<String, dynamic>> get _userDoc =>
      FirebaseFirestore.instance
          .collection('users')
          .doc(FirebaseAuth.instance.currentUser!.uid);

  @override
  void initState() {
    super.initState();
    _accepted = _load();
  }

  Future<bool> _load() async {
    final snap = await _userDoc.get();
    final version = snap.data()?['consentVersion'];
    return version is int && version >= kConsentVersion;
  }

  Future<void> _accept() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await _userDoc.set({
        'consentVersion': kConsentVersion,
        'consentAcceptedAt': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));
      if (!mounted) return;
      setState(() => _accepted = Future.value(true));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'Could not save your choice: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _declineAndSignOut() async {
    try {
      await GoogleSignIn().signOut();
    } catch (_) {}
    await FirebaseAuth.instance.signOut();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _accepted,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        if (snap.hasError) {
          return Scaffold(
            body: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'Could not check your settings:\n${snap.error}',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: () => setState(() => _accepted = _load()),
                      child: const Text('Try again'),
                    ),
                  ],
                ),
              ),
            ),
          );
        }

        if (snap.data == true) return widget.child;

        return _buildConsent(context);
      },
    );
  }

  Widget _section(String title, List<String> lines) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 6),
          ...lines.map(
            (l) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('•  '),
                  Expanded(child: Text(l)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildConsent(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Before you start'),
          automaticallyImplyLeading: false,
        ),
        body: SafeArea(
          child: Column(
            children: [
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    _section('Your data', const [
                      'SwapCycle stores your name, QIU email, your listings '
                          'and preferences, ratings you give or receive, and '
                          'the messages, photos and locations you send in '
                          'chat.',
                      'Chats are visible only to the two people in them. '
                          'Other QIU students can see your name, listings '
                          'and ratings.',
                      'Sharing your location in chat is optional and only '
                          'sends a one-time snapshot.',
                    ]),
                    _section('AI suggestions', const [
                      'AI helps read your preference text and can explain '
                          'why a match was chosen. These are suggestions, '
                          'not guarantees.',
                      'The AI cannot create or change a match, and nothing '
                          'is final until everyone in the swap confirms.',
                      'An explanation may mention details you wrote in '
                          'your preference (for example that you need the '
                          'item urgently), and it is shown only to the '
                          'people in the same swap.',
                    ]),
                    _section('Meeting safely', kSafetyTips),
                  ],
                ),
              ),
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
                child: Column(
                  children: [
                    CheckboxListTile(
                      value: _agreed,
                      onChanged: _saving
                          ? null
                          : (v) => setState(() => _agreed = v ?? false),
                      controlAffinity: ListTileControlAffinity.leading,
                      contentPadding: EdgeInsets.zero,
                      title: const Text(
                        'I have read this and I agree.',
                      ),
                    ),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Text(
                          _error!,
                          style: const TextStyle(color: Colors.red),
                        ),
                      ),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: (_agreed && !_saving) ? _accept : null,
                        child: _saving
                            ? const SizedBox(
                                height: 18,
                                width: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Text('Continue'),
                      ),
                    ),
                    TextButton(
                      onPressed: _saving ? null : _declineAndSignOut,
                      child: const Text('Decline and sign out'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
