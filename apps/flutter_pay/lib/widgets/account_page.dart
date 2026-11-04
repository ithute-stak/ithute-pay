import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../services/account_session.dart';

class AccountPage extends StatefulWidget {
  const AccountPage({super.key});

  @override
  State<AccountPage> createState() => _AccountPageState();
}

class _AccountPageState extends State<AccountPage> {
  late final http.Client _client;
  late final AccountSessionService _sessionService;
  AccountSession? _session;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _client = http.Client();
    _sessionService = AccountSessionService(
      client: _client,
      endpoint: Uri.base.resolve('/mobile-session'),
    );
    _refresh();
  }

  Future<void> _refresh() async {
    if (!mounted) return;
    setState(() => _loading = true);
    final result = await _sessionService.check();
    if (!mounted) return;
    setState(() {
      _session = result;
      _loading = false;
    });
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final profile = _session?.profile;
    return Card(
      color: Colors.white,
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Account', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
            const SizedBox(height: 14),
            if (_loading)
              const LinearProgressIndicator()
            else if (_session?.kind == SessionKind.signedIn && profile != null) ...[
              const Icon(Icons.verified_user_outlined, color: Color(0xFF275DE5), size: 38),
              const SizedBox(height: 12),
              Text(profile.fullName, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 7),
              Text(profile.email),
              const SizedBox(height: 7),
              Text('Product role: ${profile.role}'),
              const SizedBox(height: 16),
              const Text(
                'This is the existing Ithute Pay account linked to your '
                'current browser session. Customer wallet access is not enabled.',
              ),
            ] else if (_session?.kind == SessionKind.signedOut) ...[
              const Icon(Icons.lock_outline, color: Color(0xFF63718E), size: 38),
              const SizedBox(height: 12),
              const Text('Not signed in', style: TextStyle(fontSize: 19, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              const Text(
                'No active Ithute Pay session is available for this domain. '
                'Customer login will be enabled only after central !thute Auth '
                'callback, tenant permission and mobile session testing.',
              ),
              const SizedBox(height: 12),
              const Text(
                'Existing business users can continue signing in through '
                'portal.pay.ithute.co.ls.',
              ),
            ] else if (!_loading) ...[
              const Icon(Icons.warning_amber_rounded, size: 38),
              const SizedBox(height: 12),
              const Text('Unable to verify session right now.'),
            ],
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: _loading ? null : _refresh,
              icon: const Icon(Icons.refresh),
              label: const Text('Recheck session'),
            ),
            const SizedBox(height: 14),
            const Text(
              'This screen is read-only. It does not send passwords, '
              'store access tokens, access merchant API keys, or perform payments.',
              style: TextStyle(fontSize: 12, color: Color(0xFF63718E)),
            ),
          ],
        ),
      ),
    );
  }
}
