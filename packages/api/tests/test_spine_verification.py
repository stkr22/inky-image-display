"""Tests for comparing transcribed book spines against what was requested.

The comparison decides whether a generated shelf is kept or regenerated, so it
has to be strict about letters and forgiving about typography — a regeneration
triggered by an en-dash costs a real image generation.
"""

from inky_image_display_shared.ai import SpineReading, normalize_printed, spines_match

_EXPECTED = [("Der Grüne Fluss", "Anna Bergström"), ("Nachtwache", "Peter Vane")]


def _readings(*pairs: tuple[str, str]) -> list[SpineReading]:
    return [SpineReading(title=t, author=a) for t, a in pairs]


def test_exact_transcription_matches():
    assert spines_match(_EXPECTED, _readings(*_EXPECTED))


def test_case_and_dash_variants_still_match():
    # The model renders shelves in caps about half the time and swaps hyphens
    # for en-dashes freely; neither changes what a reader sees.
    assert spines_match(
        [("Nordlicht - Erster Teil", "Peter Vane")],
        _readings(("NORDLICHT – ERSTER TEIL", "Peter Vane")),  # noqa: RUF001 — the en dash is the point
    )


def test_surrounding_and_repeated_whitespace_is_ignored():
    assert spines_match(_EXPECTED, _readings(("  Der Grüne   Fluss ", "Anna Bergström"), _EXPECTED[1]))


def test_a_single_dropped_letter_fails():
    # The real failure mode: a spine shipped to a panel missing one letter.
    assert not spines_match(_EXPECTED, _readings(("Der Grüne Flus", "Anna Bergström"), _EXPECTED[1]))


def test_sharp_s_and_double_s_are_treated_as_the_same_word():
    # casefold() folds ß to ss, which is what we want: both spellings are
    # the same German word, and regenerating over the model picking the
    # other orthography would burn a generation for nothing.
    assert spines_match([("Der Grüne Fluss", "Anna Bergström")], _readings(("Der Grüne Fluß", "Anna Bergström")))


def test_a_wrong_author_fails():
    assert not spines_match(_EXPECTED, _readings(_EXPECTED[0], ("Nachtwache", "Anna Bergström")))


def test_an_extra_invented_book_fails():
    # An image model has produced a seventh book on a six-book shelf; the
    # titles it does carry all being right must not make that pass.
    assert not spines_match(_EXPECTED, _readings(*_EXPECTED, ("Nachzügler", "Niemand")))


def test_a_missing_book_fails():
    assert not spines_match(_EXPECTED, _readings(_EXPECTED[0]))


def test_reordered_spines_fail():
    # Order is part of the request: the shelf is generated left to right.
    assert not spines_match(_EXPECTED, _readings(_EXPECTED[1], _EXPECTED[0]))


def test_umlauts_are_preserved_not_folded_away():
    # Casefolding must not turn "Bergström" into "Bergstroem" or the check
    # would accept a spine that visibly differs.
    assert not spines_match([("Der Grüne Fluss", "Anna Bergstroem")], _readings(_EXPECTED[0]))


def test_normalize_keeps_letters_and_folds_typography():
    assert normalize_printed("  DER  GRÜNE FLUSS – Teil 1 ") == "der grüne fluss - teil 1"  # noqa: RUF001 — en dash is the input
