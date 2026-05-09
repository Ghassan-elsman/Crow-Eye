"""
DEPRECATED: This module has been moved to eye.backends.local_cli.cli_profiles

This file provides backward compatibility imports. The backend architecture has been
reorganized to separate the three connection approaches (Cloud API, Local CLI, Direct
Local Servers) into dedicated directories.

Please update your imports to:
    from eye.backends.local_cli.cli_profiles import CLI_PROFILES, get_profile, list_supported_backends
    from eye.backends.base import LLMBackend

The old import paths will continue to work but will emit deprecation warnings.
"""

import warnings

# Emit deprecation warning when this module is imported
warnings.warn(
    "eye.cli_agents.cli_profiles is deprecated and will be removed in a future version. "
    "Please use eye.backends.local_cli.cli_profiles instead.",
    DeprecationWarning,
    stacklevel=2
)

# Forward imports from new locations
from eye.backends.base import LLMBackend
from eye.backends.local_cli.cli_profiles import (
    CLI_PROFILES,
    get_profile,
    list_supported_backends
)

__all__ = ['LLMBackend', 'CLI_PROFILES', 'get_profile', 'list_supported_backends']
