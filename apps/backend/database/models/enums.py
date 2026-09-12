import enum


class UserRole(str, enum.Enum):
    SUPERADMIN = "platform_super_admin"
    PLATFORM_ADMIN = "platform_admin"
    OPERATIONS = "operations"
    FINANCE = "finance"
    DEVELOPER = "developer"
    SUPPORT = "support"
    COMPLIANCE = "compliance"
    AUDITOR = "auditor"


class MerchantStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class ApplicationEnvironment(str, enum.Enum):
    TEST = "test"
    LIVE = "live"


class ResourceStatus(str, enum.Enum):
    CREATED = "created"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    AWAITING_CUSTOMER = "awaiting_customer"
    PROCESSING = "processing"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REVERSED = "reversed"
    PARTIALLY_REVERSED = "partially_reversed"


class PaymentProvider(str, enum.Enum):
    MPESA = "mpesa"
    SIMULATOR = "simulator"
    ECOCASH = "ecocash"
    BANK = "bank"


class TransactionDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MandateStatus(str, enum.Enum):
    CREATED = "created"
    PROCESSING = "processing"
    ACTIVE = "active"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
