import 'dart:convert';
import 'package:http/http.dart' as http;

enum BackendState { available, unavailable }

class BackendStatus {
  final BackendState state;
  final String message;
  const BackendStatus(this.state, this.message);

  bool get available => state == BackendState.available;
}

class BackendStatusService {
  final http.Client client;
  final Uri endpoint;
  const BackendStatusService({required this.client, required this.endpoint});

  Future<BackendStatus> check() async {
    try {
      final response = await client.get(
        endpoint,
        headers: const {'Accept': 'application/json'},
      ).timeout(const Duration(seconds: 7));
      if (response.statusCode != 200) {
        return const BackendStatus(BackendState.unavailable, 'Service temporarily unavailable');
      }
      final payload = jsonDecode(response.body);
      if (payload is Map<String, dynamic> && payload['status'] == 'healthy') {
        return const BackendStatus(BackendState.available, 'Service available');
      }
    } catch (_) {
      // Do not expose infrastructure or network error details to users.
    }
    return const BackendStatus(BackendState.unavailable, 'Service temporarily unavailable');
  }
}
