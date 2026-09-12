"""PayPal provider package boundary.

PayPal currently owns dedicated API/router flows rather than the generic mobile-money
provider interface. Provider-specific orchestration should be added here instead of
expanding the shared integration registry.
"""

PROVIDER_ID = "paypal"
