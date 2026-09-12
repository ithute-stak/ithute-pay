from __future__ import annotations


def build_error_response_content(
    *,
    request_id: str,
    message: str = 'An unexpected server error occurred.',
    technical_detail: str | None = None,
) -> dict:
    content = {
        'detail': message,
        'request_id': request_id,
    }
    if technical_detail:
        content['technical_detail'] = technical_detail
    return content
