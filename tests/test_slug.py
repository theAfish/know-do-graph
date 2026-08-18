from core.utils.slug import slug_from_title


def test_slug_from_title_handles_words_and_scientific_units() -> None:
    assert slug_from_title("Ångström unit") == "angstrom-unit"
    assert slug_from_title("Cutoff 3 Å") == "cutoff-3-angstrom"
    assert slug_from_title("μ and µ both mean micro") == "micro-and-micro-both-mean-micro"
