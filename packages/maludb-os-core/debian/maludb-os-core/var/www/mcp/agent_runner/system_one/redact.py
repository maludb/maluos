"""Redaction and fingerprinting for what the Sysadmin reads (db/145; docs/build-specs/system-one-harness.md).

Nothing read from a log is stored or sent to JEV before it passes through redact(): tokens, keys,
passwords, long hex, email addresses, public IP addresses and request bodies are masked. The raw logs
stay where they are. fingerprint() then masks what varies between occurrences (numbers, ids, times,
quoted values) so repeats of one problem group into one event.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re

MAX_LINE = 600

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (re.compile(r"\bosapp_[A-Za-z0-9]+"), "osapp_[REDACTED]"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{12,}"), r"\1-[REDACTED]"),
    (re.compile(r"(?i)\b([a-z0-9_]*(?:key|token|secret|password|passwd|pwd|api_key|apikey|authorization|cookie|session)[a-z0-9_]*)"
                r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)\b(CSTSID|PHPSESSID)=[A-Za-z0-9,-]+"), r"\1=[REDACTED]"),
    (re.compile(r"\b\d+\.\d{9,}\.\d+\.[a-f0-9]{16,}\b"), "[TOKEN]"),                       # our signed token shapes
    (re.compile(r"\b[a-f0-9]{32,}\b", re.I), "[HEX]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "[JWT]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?i)(request body|body|payload|data)\s*[:=]\s*(\{.*\}|\[.*\])"), r"\1: [BODY]"),
]
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _mask_ip(match: re.Match) -> str:
    text = match.group(0)
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return text
    return text if (ip.is_loopback or ip.is_private) else "[IP]"


def redact(line: str) -> str:
    """The line with every secret-shaped thing masked, trimmed to MAX_LINE."""
    text = (line or "").replace("\x00", "")
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    text = _IPV4.sub(_mask_ip, text)
    return text[:MAX_LINE]


_VARYING: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    (re.compile(r"\[(Mon|Tue|Wed|Thu|Fri|Sat|Sun) [^\]]+\]"), "<ts>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\"[^\"]{0,200}\"|'[^']{0,200}'"), "<str>"),
    (re.compile(r"\b(pid|tid|client|port)\s*\d+", re.I), r"\1 <n>"),
    (re.compile(r"\d+"), "<n>"),
]


def fingerprint(source: str, redacted_line: str) -> str:
    """One problem's identity: its source and the line with everything that varies masked."""
    shape = redacted_line
    for pattern, replacement in _VARYING:
        shape = pattern.sub(replacement, shape)
    shape = re.sub(r"\s+", " ", shape).strip()[:300]
    return hashlib.sha256(f"{source}|{shape}".encode()).hexdigest()[:40]
