"""Label normalisation and cross-vocabulary alias matching between recognition heads."""
from __future__ import annotations

import re

_BRACKET = re.compile(r"\[[^\]]*\]")
_PAREN = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9]")


def aliases(label: str) -> set[str]:
    """'Television/T.V.' -> {'television', 'tv'}; 'Die [VEB]/Dead' -> {'die', 'dead'};
    'Cold (Water)' -> {'cold', 'coldwater'}."""
    out: set[str] = set()
    base = _BRACKET.sub(" ", label)
    for part in base.split("/"):
        p = part.strip().lower()
        if not p:
            continue
        out.add(_NON_ALNUM.sub("", p))
        out.add(_NON_ALNUM.sub("", _PAREN.sub(" ", p)))
    out.discard("")
    return out


def norm_key(label: str) -> str:
    """Canonical key for a label: first alias (cleaned of parentheses)."""
    a = _NON_ALNUM.sub("", _PAREN.sub(" ", _BRACKET.sub(" ", label)).split("/")[0].strip().lower())
    return a or _NON_ALNUM.sub("", label.lower())


def display_name(label: str) -> str:
    """Human-readable form: strip bracket tags, keep first alternative."""
    s = _BRACKET.sub("", label).strip()
    return s if s else label


class AliasIndex:
    """Maps labels of a secondary head to labels of the primary head by normalised aliases."""

    def __init__(self, primary_labels: list[str], secondary_labels: list[str]):
        prim: dict[str, str] = {}
        for lab in primary_labels:
            for a in aliases(lab):
                prim.setdefault(a, lab)
        self.sec_to_prim: dict[str, str | None] = {}
        for lab in secondary_labels:
            hit = None
            for a in aliases(lab) | {lab.lower()}:
                if a in prim:
                    hit = prim[a]
                    break
            self.sec_to_prim[lab] = hit

    def map(self, secondary_label: str) -> str | None:
        return self.sec_to_prim.get(secondary_label)

    @property
    def n_mapped(self) -> int:
        return sum(1 for v in self.sec_to_prim.values() if v)
