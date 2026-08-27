#!/usr/bin/env python3
"""Final PDF stage. Browser automation is intentionally not imported or executed."""
from pdf_pipeline import build as create_combined, main

__all__ = ["create_combined", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
