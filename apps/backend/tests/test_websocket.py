def test_platform_websocket_session(client, admin_token):
    response = client.post(
        '/api/v1/auth/websocket-session',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert response.status_code == 200, response.text
    assert response.json()['expires_in'] > 0

    with client.websocket_connect('/api/v1/ws?client_id=test-dashboard') as socket:
        payload = socket.receive_json()
        assert payload['type'] == 'SOCKET_CONNECTED'
        assert 'platform' in payload['channels']
        socket.send_text('ping')
        assert socket.receive_text() == 'pong'
