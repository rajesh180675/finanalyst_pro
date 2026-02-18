"""
tests/conftest.py
=================
Shared pytest fixtures for FinAnalyst Pro test suite.
"""
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
