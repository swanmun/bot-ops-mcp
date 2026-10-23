"""Scrub secrets and account-size hints from anything the server returns.

Tool results go to the model provider, so they must not carry API keys, bot tokens,
IP addresses or dollar amounts (dollar amounts reveal account size; the tools report % and R instead).
Quantities and prices stay — they are needed to diagnose mismatches.

[한국어] 서버가 돌려주는 모든 것에서 비밀값과 계좌 규모를 짐작하게 하는 정보를 지운다.

도구 결과는 모델 제공사로 넘어간다. 그래서 API 키, 봇 토큰, IP 주소, 달러 금액이 들어 있으면 안 된다
(달러 금액은 계좌 규모를 드러낸다. 도구는 대신 %와 R로 보고한다).
수량과 가격은 남긴다. 불일치를 진단하려면 필요하기 때문이다.
"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "<telegram-token>"),   # Telegram bot token / Telegram 봇 토큰
    (re.compile(r"\b[A-Za-z0-9]{48,}\b"), "<secret>"),                       # exchange API key / secret, signatures / 거래소 API 키·시크릿, 서명
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),                    # IPv4 (server, VPN) / IPv4(서버, VPN)
    (re.compile(r"\$\s?-?[\d,]+(?:\.\d+)?"), "$<amount>"),                   # dollar amounts / 달러 금액
    (re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*\S+"), r"\1=<hidden>"),
]


def text(s: str) -> str:
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    return s


def deep(obj):
    """Apply text() to every string inside dicts / lists.

    [한국어] dict / list 안의 모든 문자열에 text()를 적용한다.
    """
    if isinstance(obj, str):
        return text(obj)
    if isinstance(obj, dict):
        return {k: deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep(v) for v in obj]
    return obj
