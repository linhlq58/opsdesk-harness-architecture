"""Business policies: pure functions that decide.

No I/O, no clock reads (``now`` is a parameter), no config reads (rules are
parameters). Query policies return a ``Decision``; command policies return a new
entity or raise a ``DomainError``.
"""
