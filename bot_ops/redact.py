"""Scrub secrets and account-size hints from anything the server returns.

Tool results go to the model provider, so they must not carry API keys, bot tokens,
IP addresses or dollar amounts (dollar amounts reveal account size; the tools report % and R instead).
Quantities and prices stay — they are needed to diagnose mismatches.
"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "<telegram-token>"),   # Telegram bot token
    (re.compile(r"\b[A-Za-z0-9]{48,}\b"), "<secret>"),                       # exchange API key / secret, signatures
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),                    # IPv4 (server, VPN)
    (re.compile(r"\$\s?-?[\d,]+(?:\.\d+)?"), "$<amount>"),                   # dollar amounts
    (re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*\S+"), r"\1=<hidden>"),
]


def text(s: str) -> str:
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    return s


def deep(obj):
    """Apply text() to every string inside dicts / lists."""
    if isinstance(obj, str):
        return text(obj)
    if isinstance(obj, dict):
        return {k: deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep(v) for v in obj]
    return obj
