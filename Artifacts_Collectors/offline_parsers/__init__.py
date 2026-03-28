"""
Offline Parsers Package

This package contains offline forensic artifact parsers that can analyze
artifacts without requiring a live system.
"""

# Export main parsers
try:
    from .offline_RegClaw import reg_Claw
    __all__ = ['reg_Claw']
except ImportError:
    pass
