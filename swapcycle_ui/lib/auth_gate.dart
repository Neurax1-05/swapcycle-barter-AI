import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import 'consent_gate.dart';
import 'login_screen.dart';
import 'main.dart' show ListingFeedScreen; // your existing screen

class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<User?>(
      stream: FirebaseAuth.instance.authStateChanges(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        if (snapshot.hasData) {
          // First login: show the consent / safety popup once.
          return const ConsentGate(child: ListingFeedScreen());
        }
        return const LoginScreen();
      },
    );
  }
}
