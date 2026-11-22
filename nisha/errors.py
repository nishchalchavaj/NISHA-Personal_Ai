class NishaError(Exception):
    """An actionable, safe-to-display application error."""


class ConfigurationError(NishaError):
    pass


class PrivacyError(NishaError):
    pass


class OperationCancelled(NishaError):
    """The user stopped this turn before further output or actions."""


class ModelUnavailable(NishaError):
    pass


class OutputLimitReached(ModelUnavailable):
    """A valid response segment reached its output budget; it can be continued."""


class ContextTooLarge(NishaError):
    pass
