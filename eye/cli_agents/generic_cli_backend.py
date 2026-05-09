"""
DEPRECATED: This module has been moved to eye.backends.local_cli.generic_cli_backend

This file provides backward compatibility imports. Please update your imports to:
from eye.backends.local_cli.generic_cli_backend import GenericCLIBackend

The GenericCLIBackend class is now part of the reorganized backend architecture where
each connection approach (Cloud API, Local CLI, Direct Local Servers) has its own
dedicated directory structure for better maintainability and clarity.
"""

import warnings

warnings.warn(
    "eye.cli_agents.generic_cli_backend is deprecated. "
    "Use eye.backends.local_cli.generic_cli_backend instead.",
    DeprecationWarning,
    stacklevel=2
)

from eye.backends.local_cli.generic_cli_backend import GenericCLIBackend

__all__ = ['GenericCLIBackend']
