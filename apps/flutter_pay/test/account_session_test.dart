import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ithutepay_mobile/services/account_session.dart';

void main() {
  final endpoint = Uri.parse('https://pay.ithute.co.ls/mobile-session');

  test('valid authenticated profile is accepted', () async {
    final client = MockClient((request) async {
      expect(request.url.path, '/mobile-session');
      expect(request.method, 'GET');
      return http.Response(
        '{"id":"user-123","full_name":"Demo User","email":"demo@example.com","role":"merchant"}',
        200,
      );
    });
    final result = await AccountSessionService(client: client, endpoint: endpoint).check();
    expect(result.kind, SessionKind.signedIn);
    expect(result.profile?.fullName, 'Demo User');
    client.close();
  });

  test('unauthorized response is signed out without identity', () async {
    final client = MockClient((_) async => http.Response('Unauthorized', 401));
    final result = await AccountSessionService(client: client, endpoint: endpoint).check();
    expect(result.kind, SessionKind.signedOut);
    expect(result.profile, isNull);
    client.close();
  });

  test('forbidden response is also signed out', () async {
    final client = MockClient((_) async => http.Response('Forbidden', 403));
    final result = await AccountSessionService(client: client, endpoint: endpoint).check();
    expect(result.kind, SessionKind.signedOut);
    client.close();
  });

  test('error response does not produce identity', () async {
    final client = MockClient((_) async => http.Response('Unavailable', 502));
    final result = await AccountSessionService(client: client, endpoint: endpoint).check();
    expect(result.kind, SessionKind.unavailable);
    expect(result.profile, isNull);
    client.close();
  });

  test('malformed JSON does not produce identity', () async {
    final client = MockClient((_) async => http.Response('{"email":"demo@example.com"}', 200));
    final result = await AccountSessionService(client: client, endpoint: endpoint).check();
    expect(result.kind, SessionKind.unavailable);
    expect(result.profile, isNull);
    client.close();
  });
}
