"""Inbound texts: the public webhook that lets a lead's SMS into the system safely.

The signature is checked first, with no database access. Only then is the tenant in the URL trusted.
"""
