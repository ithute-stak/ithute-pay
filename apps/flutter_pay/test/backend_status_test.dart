import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ithutepay_mobile/services/backend_status.dart';

void main() {
  final endpoint = Uri.parse('https://pay.ithute.co.ls/service-health');

  test('healthy backend response is available', () async {
    final client = MockClient((_) async =>
        http.Response('{"status":"healthy","product":"Ithute Pay"}', 200));
    final status = await BackendStatusService(client: client, endpoint: endpoint).check();
    expect(status.available, isTrue);
    client.close();
  });

  test('rejects non-200 status without exposing details', () async {
    final client = MockClient((_) async => http.Response('Gateway error', 502));
    final status = await BackendStatusService(client: client, endpoint: endpoint).check();
    expect(status.available, isFalse);
    client.close();
  });

  test('rejects unexpected JSON shape', () async {
    final client = MockClient((_) async => http.Response('{"status":"error"}', 200));
    final status = await BackendStatusService(client: client, endpoint: endpoint).check();
    expect(status.available, isFalse);
    client.close();
  });
}
