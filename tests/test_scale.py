"""Scale tests: title-block text -> factor, ambiguity -> None, M2 guard.

The M2 guard: the fallback regex MUST require the word SCALE or SKALA. On real
sheets (no scale line) a bare 1[:/]N matches "REV 1/2" (factor 2) and a sheet
code "A1:1000" (factor 1000) — with the word requirement they yield None
(human QA gate) instead of silently wrong quantities.
"""
from takeoff.scale import Scale, apply_override, parse_scale


def test_parse_title_block():
    assert parse_scale("SCALE 1:100") == Scale(factor=100, source="text")


def test_parse_ambiguous():
    assert parse_scale("SCALE 1:100, 1:250") is None


def test_m_per_pt():
    s = Scale(factor=100, source="text")
    assert abs(s.m_per_pt() - 0.03527778) < 1e-6   # 100 * 25.4/72/1000


def test_mm_per_pt_scale_independent():
    s = Scale(factor=100, source="text")
    assert abs(s.mm_per_pt() - 25.4 / 72) < 1e-12


def test_m2_fallback_requires_scale_word():
    # Bare 1[:/]N is never accepted (M2): REV 1/2 -> factor 2, A1:1000 -> factor 1000.
    assert parse_scale("REV 1/2") is None
    assert parse_scale("A1:1000") is None
    # SKALA is the BM fallback word on the same sheets.
    assert parse_scale("DETAIL SKALA 1:50") == Scale(factor=50, source="text")


def test_apply_override():
    assert apply_override("", 50) == Scale(factor=50, source="user_override")
