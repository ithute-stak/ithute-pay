from contextvars import ContextVar


current_user_id: ContextVar[str | None] = ContextVar('current_user_id', default=None)
current_request_id: ContextVar[str | None] = ContextVar('current_request_id', default=None)
current_ip_address: ContextVar[str | None] = ContextVar('current_ip_address', default=None)
current_user_agent: ContextVar[str | None] = ContextVar('current_user_agent', default=None)
current_application_id: ContextVar[str | None] = ContextVar('current_application_id', default=None)
current_merchant_id: ContextVar[str | None] = ContextVar('current_merchant_id', default=None)
