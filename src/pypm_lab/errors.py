"""Project-specific exception hierarchy."""
 
from __future__ import annotations


class PyPMError(Exception):
    """Base class for expected PyPM Lab errors."""


class VersionError(PyPMError, ValueError):
    """Raised when a semantic version is malformed."""


class ConstraintError(PyPMError, ValueError):
    """Raised when a version constraint is malformed."""


class RequirementError(PyPMError, ValueError):
    """Raised when a package requirement is malformed."""


class ManifestError(PyPMError):
    """Raised when a project manifest cannot be read or validated."""


class LockfileError(PyPMError):
    """Raised when a lockfile cannot be read or validated."""


class RegistryError(PyPMError):
    """Raised for registry loading and query failures."""


class RegistryValidationError(RegistryError):
    """Raised with all readable registry validation failures."""

    def __init__(self, errors: list[str] | tuple[str, ...]):
        self.errors = tuple(errors)
        message = "Registry validation failed:\n" + "\n".join(
            f"  - {error}" for error in self.errors
        )
        super().__init__(message)


class ResolutionError(PyPMError):
    """Raised for dependency resolution failures."""


class GraphError(PyPMError):
    """Raised when graph operations fail."""


class IntegrityError(PyPMError):
    """Raised when integrity verification fails."""


class InstallError(PyPMError):
    """Raised when installation fails."""
