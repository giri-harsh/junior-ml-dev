"""Untrusted-data handling: sanitise, score, alias and delimit anything that came from a dataset.

Dataset values, column names, filenames and tool outputs are DATA. They reach LLM-visible text only
through these helpers, inside delimited UNTRUSTED slots; flagged names are replaced by aliases.
"""

from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass, field

MAX_NAME = 60
MAX_CELL = 120
FLAG_THRESHOLD = 0.5
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

_VERB = r"\b(deploy|approve|override|exfiltrate|send)"
_OBJECT = r"(model|token|data|labels?)\b"
# (pattern, weight): weights add up, capped at 1.0
SIGNALS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)", re.I), 0.7),
    (re.compile(r"(system|developer)\s+(prompt|message|instruction)", re.I), 0.5),
    (re.compile(r"\b(you are now|act as|new instructions?|disregard)\b", re.I), 0.5),
    (re.compile(r"(^|\s)(assistant|system|user)\s*:", re.I), 0.4),
    (re.compile(r"scorer|test_labels|hidden|/etc/|\.env|\.ssh", re.I), 0.4),
    (re.compile(r"https?://|www\.", re.I), 0.4),
    (re.compile(r"\b(rm\s+-rf|curl|wget|import\s+(os|socket|subprocess))\b", re.I), 0.5),
    (re.compile(_VERB + r"\b.*\b" + _OBJECT, re.I), 0.4),
    (re.compile(r"(change|set|switch)\s+(the\s+)?target", re.I), 0.5),
    (re.compile(r"```|<\||\|>|</?untrusted", re.I), 0.5),
    (re.compile(r"\b(base64|eval|exec)\b", re.I), 0.3),
    # added from DEV evasion cases only (see benchmarks/injection/evasion.py)
    (re.compile(r"\bignora\s+(\w+\s+){0,2}(instrucciones|istruzioni|instru..es)\b", re.I), 0.7),
    (re.compile(r"\bpay no (heed|attention) to\b", re.I), 0.5),
]  # fmt: skip


def sanitize_text(value: object, max_len: int = MAX_CELL) -> str:
    """NFKC-normalise, strip control/zero-width/bidi characters, collapse whitespace, cap length."""
    text = unicodedata.normalize("NFKC", str(value))
    text = _CONTROL.sub(" ", _INVISIBLE.sub("", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _score_text(text: str) -> float:
    return min(1.0, sum(w for pat, w in SIGNALS if pat.search(text)))


def injection_score_v0(value: object) -> float:
    """The original single-view scorer, kept so before/after numbers stay reproducible."""
    return _score_text(sanitize_text(value, max_len=10_000))


_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)
_B64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_SINGLE_CHARS = re.compile(r"(?:\S )+\S")
_WIDE_GAP = re.compile(r"\s{2,}")
_INNER_SEP = re.compile(r"(?<=[^\W_])[-._](?=[^\W_])")


def _keep_ws(value: object, max_len: int = 10_000) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return _CONTROL.sub(" ", _INVISIBLE.sub("", text))[:max_len]


def _join_spaced(text: str) -> str:
    """'i g n o r e   a l l' -> 'ignore all' (words split on 2+ spaces, letters on one)."""
    parts = [p.replace(" ", "") if _SINGLE_CHARS.fullmatch(p) else p for p in _WIDE_GAP.split(text)]
    return " ".join(parts)


def _decoded_chunks(text: str) -> list[str]:
    out = []
    for m in _B64.finditer(text):
        try:
            raw = base64.b64decode(m.group(0), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if raw.isprintable():
            out.append(raw)
    return out


def views(value: object) -> list[str]:
    """Text views a payload may hide in: as-is, leet-folded, letter-joined, de-separated,
    reversed, and base64-decoded. Each is scored independently; the maximum counts."""
    raw = _keep_ws(value)
    base = sanitize_text(raw, 10_000)
    leet = raw.lower().translate(_LEET)
    out = [base, sanitize_text(leet, 10_000)]
    for v in (raw, leet):
        out.append(sanitize_text(_INNER_SEP.sub("", _join_spaced(v)), 10_000))
    out.append(base[::-1])
    out.append(" ".join(w[::-1] for w in base.split()))  # each word reversed in place
    out += [sanitize_text(d, 10_000) for d in _decoded_chunks(raw)]
    return out


def injection_score(value: object) -> float:
    return max(_score_text(v) for v in views(value))


def is_flagged(value: object) -> bool:
    return injection_score(value) >= FLAG_THRESHOLD


def render_untrusted(kind: str, value: object, max_len: int = MAX_CELL) -> str:
    """The only way untrusted text enters an LLM-visible string."""
    clean = sanitize_text(value, max_len).replace("<", "(").replace(">", ")")
    flag = ' flagged="true"' if is_flagged(value) else ""
    return f'<UNTRUSTED kind="{kind}"{flag}>{clean}</UNTRUSTED>'


@dataclass
class AliasMap:
    """Maps flagged or oversized names to stable aliases (`col_017`); the map stays server-side."""

    forward: dict[str, str] = field(default_factory=dict)

    def alias(self, name: str, index: int) -> str:
        clean = sanitize_text(name, max_len=10_000)
        if is_flagged(name) or len(clean) > MAX_NAME or clean != name:
            self.forward[name] = f"col_{index:03d}"
            return self.forward[name]
        return name

    def reverse(self) -> dict[str, str]:
        return {v: k for k, v in self.forward.items()}


def visible_columns(columns: list[str]) -> tuple[list[str], AliasMap]:
    amap = AliasMap()
    return [amap.alias(c, i) for i, c in enumerate(columns)], amap


class UntrustedInInstructions(ValueError):
    pass


def assert_clean_instructions(instruction_text: str, untrusted_values: list[str]) -> None:
    """Packer guard: raw untrusted text must never sit in a system/instruction slot."""
    for v in untrusted_values:
        clean = sanitize_text(v, max_len=10_000)
        if len(clean) >= 8 and (clean in instruction_text or v in instruction_text):
            raise UntrustedInInstructions(
                f"untrusted text found in instruction slot: {clean[:30]!r}"
            )
