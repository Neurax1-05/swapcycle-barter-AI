import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:google_sign_in/google_sign_in.dart';

const String kAllowedDomain = 'qiu.edu.my';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  bool _busy = false;
  String? _error;

  // Client-side check is UX only — it stops most mistakes early, but the
  // real enforcement is the beforeSignIn/beforeUserCreated blocking
  // function deployed to Cloud Functions (see functions/index.js).
  bool _isAllowedEmail(String email) =>
      email.trim().toLowerCase().endsWith('@$kAllowedDomain');

  Future<void> _signInWithGoogle() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final googleSignIn = GoogleSignIn(
        // Nudges Google's account picker toward the QIU workspace — a
        // hint only. The blocking function is what actually enforces it.
        hostedDomain: kAllowedDomain,
      );
      final googleUser = await googleSignIn.signIn();
      if (googleUser == null) {
        setState(() => _busy = false);
        return; // user cancelled the picker
      }

      if (!_isAllowedEmail(googleUser.email)) {
        await googleSignIn.signOut();
        setState(() {
          _error = 'Please sign in with your @$kAllowedDomain account.';
          _busy = false;
        });
        return;
      }

      final googleAuth = await googleUser.authentication;
      final credential = GoogleAuthProvider.credential(
        accessToken: googleAuth.accessToken,
        idToken: googleAuth.idToken,
      );
      await FirebaseAuth.instance.signInWithCredential(credential);
      // If the blocking function rejects this user server-side, this
      // throws here with a FirebaseAuthException from the function.
    } on FirebaseAuthException catch (e) {
      setState(() => _error = e.message ?? 'Sign-in failed.');
    } catch (e) {
      setState(() => _error = 'Sign-in failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.sync_alt, size: 48),
                const SizedBox(height: 12),
                const Text(
                  'SwapCycle',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 4),
                Text(
                  'Sign in with your @$kAllowedDomain account',
                  style: const TextStyle(color: Colors.grey),
                ),
                const SizedBox(height: 24),
                ElevatedButton.icon(
                  onPressed: _busy ? null : _signInWithGoogle,
                  icon: const Icon(Icons.g_mobiledata),
                  label: _busy
                      ? const SizedBox(
                          height: 18,
                          width: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Sign in with Google'),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 16),
                  Text(_error!, style: const TextStyle(color: Colors.red)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
