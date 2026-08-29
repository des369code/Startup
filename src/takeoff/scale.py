"""Drawing scale: parse title-block text, convert paper points -> world units."""
import re
from dataclasses import dataclass


@dataclass
class Scale:
    factor: int                # "1:100" -> 100
    source: str                # "text" | "user_override"

    def m_per_pt(self) -> float:   # one paper point -> world metres
        return self.factor * 25.4 / 72 / 1000

    def mm_per_pt(self) -> float:  # one paper point -> mm (scale-independent)
        return 25.4 / 72


# Word-anchored ratio: the ONLY accepted form (M2 — a bare 1[:/]N matches
# "REV 1/2" (factor 2) and a sheet code "A1:1000" (factor 1000) on real sheets
# with no scale line, where the fallback is the only path).
_ANCHORED = re.compile(r"(?:SCALE|SKALA)\s*1\s*[:/]\s*(\d+)")
# Every 1:N ratio on the text: drives AMBIGUITY detection, never acceptance.
_RAW = re.compile(r"1\s*[:/]\s*(\d+)")


def parse_scale(text: str) -> Scale | None:
    """Parse the drawing scale from (upper) title-block text.

    None when there is no SCALE/SKALA declaration (bare ratios like "REV 1/2"
    are never trusted — M2), or when >=2 distinct ratios appear (ambiguity;
    caller flags in QA, user override in production).
    """
    text = text.upper()
    anchored = _ANCHORED.findall(text)
    if not anchored:
        return None
    if len(set(_RAW.findall(text))) > 1:
        return None
    return Scale(factor=int(anchored[0]), source="text")


def apply_override(text: str, factor: int) -> Scale:
    # text is provenance for the caller (e.g. the scale line it matched).
    return Scale(factor=factor, source="user_override")
