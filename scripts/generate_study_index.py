#!/usr/bin/env python3
"""Compatibility exports for Study Index discovery/order helpers.

The rendered hierarchical Study Index is generated inside pdf_pipeline.py so page
numbers and destinations are resolved only after final layout.
"""
from pdf_pipeline import discover_index, load_sessions, natural_key

__all__ = ["discover_index", "load_sessions", "natural_key"]
