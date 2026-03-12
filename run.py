#!/usr/bin/env python3
"""
Mihon Linux - Entry point.
Run with: python3 run.py
"""
import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mihon.app import main

if __name__ == "__main__":
    sys.exit(main())
