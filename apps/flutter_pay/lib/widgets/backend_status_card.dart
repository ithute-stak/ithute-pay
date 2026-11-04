import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../services/backend_status.dart';

class BackendStatusCard extends StatefulWidget {
  const BackendStatusCard({super.key});

  @override
  State<BackendStatusCard> createState() => _BackendStatusCardState();
}

class _BackendStatusCardState extends State<BackendStatusCard> {
  late final http.Client _client;
  late final BackendStatusService _service;
  BackendStatus? _status;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _client = http.Client();
    // Same-origin endpoint: no cross-origin credentials or payment API access.
    _service = BackendStatusService(
      client: _client,
      endpoint: Uri.base.resolve('/service-health'),
    );
    _refresh();
  }

  Future<void> _refresh() async {
    if (!mounted) return;
    setState(() => _loading = true);
    final status = await _service.check();
    if (!mounted) return;
    setState(() {
      _status = status;
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
    final available = _status?.available ?? false;
    final icon = _loading
        ? Icons.sync
        : (available ? Icons.check_circle_outline : Icons.warning_amber_rounded);
    return Semantics(
      liveRegion: true,
      child: Card(
        elevation: 0,
        color: Colors.white,
        child: ListTile(
          leading: Icon(icon, color: available ? Colors.green.shade700 : Colors.blueGrey),
          title: const Text('Service connection', style: TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text(_loading ? 'Checking availability…' : (_status?.message ?? 'Unavailable')),
          trailing: IconButton(
            tooltip: 'Check service again',
            onPressed: _loading ? null : _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ),
      ),
    );
  }
}
