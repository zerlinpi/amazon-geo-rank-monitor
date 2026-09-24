class RankMonitorError(Exception):
    """Base error for the rank monitoring domain."""


class ProviderUnavailableError(RankMonitorError):
    """Raised when a rank provider cannot complete a probe."""


class ProviderResponseError(RankMonitorError):
    """Raised when a provider returns an unusable response."""


class RankingError(RankMonitorError):
    """Raised when ranking inputs cannot be reconciled."""


class ConfigurationError(RankMonitorError):
    """Raised when required runtime configuration is missing or invalid."""


class UpstreamBlockedError(ProviderUnavailableError):
    """Raised when the upstream presents a robot or CAPTCHA challenge."""


class GeoVerificationError(RankMonitorError):
    """Raised when requested IP or delivery geography cannot be verified."""


class BillingError(RankMonitorError):
    """Base error for credit and payment operations."""


class InsufficientCreditsError(BillingError):
    """Raised when available prepaid credits cannot cover a reservation."""
