import 'dart:convert';

import 'package:http/http.dart' as http;

enum SessionKind { signedIn, signedOut, unavailable }

class AccountProfile {
  final String id;
  final String fullName;
  final String email;
  final String role;

  const AccountProfile({
    required this.id,
    required this.fullName,
    required this.email,
    required this.role,
  });

  static AccountProfile? fromJson(Object? value) {
    if (value is! Map<String, dynamic>) return null;
    final id = value['id'];
    final fullName = value['full_name'];
    final email = value['email'];
    final role = value['role'];
    if (id is! String || id.isEmpty ||
        fullName is! String || fullName.isEmpty ||
        email is! String || email.isEmpty ||
        role is! String || role.isEmpty) {
      return null;
    }
    return AccountProfile(
      id: id,
      fullName: fullName,
      email: email,
      role: role,
    );
  }
}

class AccountSession {
  final SessionKind kind;
  final AccountProfile? profile;
  const AccountSession(this.kind, [this.profile]);
}

class AccountSessionService {
  final http.Client client;
  final Uri endpoint;
  const AccountSessionService({required this.client, required this.endpoint});

  Future<AccountSession> check() async {
    try {
      final response = await client.get(
        endpoint,
        headers: const {'Accept': 'application/json'},
      ).timeout(const Duration(seconds: 7));

      if (response.statusCode == 401 || response.statusCode == 403) {
        return const AccountSession(SessionKind.signedOut);
      }
      if (response.statusCode != 200) {
        return const AccountSession(SessionKind.unavailable);
      }

      final profile = AccountProfile.fromJson(jsonDecode(response.body));
      if (profile == null) {
        return const AccountSession(SessionKind.unavailable);
      }
      return AccountSession(SessionKind.signedIn, profile);
    } catch (_) {
      return const AccountSession(SessionKind.unavailable);
    }
  }
}
