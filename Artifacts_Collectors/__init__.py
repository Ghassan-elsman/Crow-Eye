"""
Artifacts Collectors Package

This package contains various forensic artifact collectors and parsers.
"""

# Re-export offline_RegClaw from its new location for backward compatibility
try:
    from .offline_parsers.offline_RegClaw import reg_Claw as offline_RegClaw
    __all__ = ['offline_RegClaw']
except ImportError:
    # If import fails, don't break the entire package
    pass
