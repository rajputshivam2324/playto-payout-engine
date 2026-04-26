"""
config/settings/__init__.py

Keeps Django's settings package importable.

Key design decisions:
  - Runtime entry points select local settings by default for Phase 1 runnability.
  - Production settings live separately so deployment-only database requirements do not
    make local migrations fail before Docker and Railway are introduced.
"""
