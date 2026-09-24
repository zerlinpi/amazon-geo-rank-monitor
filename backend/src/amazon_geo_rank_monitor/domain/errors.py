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
