"""Package-wide exception types.

A leaf module (imports nothing from the rest of the package) so any module --
including dependency-light ones like :mod:`hdldepends.util` -- can raise/catch
:class:`ConfigError` without dragging in any other module or dependency.
"""


class ConfigError(ValueError):
    """Raised when a configuration file fails schema validation."""
