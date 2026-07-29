"""Compatibility package for the existing Note Maker runtime modules.

The project historically executes modules directly from ``scripts/``.  Keeping
this package marker allows the unified CLI and packaged tooling to locate that
runtime without changing the established top-level import behavior.
"""
