"""H2-c: write-boundary tag convergence — ``write_policy.converge_tags``.

The full discipline table: whitelist convergence, new-word handling,
truncation, dedup (exact + case-fold keeping the established spelling),
order preservation, and empty/degenerate inputs.
"""
from AssetsManager.application.ai_tagging.write_policy import converge_tags


class TestWhitelistConvergence:
    def test_model_tags_outside_vocabulary_are_dropped(self):
        result = converge_tags(
            ["hero", "landscape", "made_up_word"],
            existing=["hero", "landscape"],
            max_tags=8,
            force_existing=True,
        )
        assert result == ["hero", "landscape"]

    def test_existing_spelling_wins_over_model_capitalization(self):
        result = converge_tags(
            ["HERO", "Landscape"],
            existing=["Hero", "Landscape"],
            max_tags=8,
            force_existing=True,
        )
        assert result == ["Hero", "Landscape"]

    def test_empty_vocabulary_drops_everything_when_forced(self):
        result = converge_tags(
            ["hero"], existing=[], max_tags=8, force_existing=True
        )
        assert result == []

    def test_casefold_beyond_lowercasing(self):
        # casefold (not lower) semantics: German sharp s folds to "ss".
        result = converge_tags(
            ["STRAßE"], existing=["strasse"], max_tags=5, force_existing=True
        )
        assert result == ["strasse"]


class TestNewWords:
    def test_new_words_kept_when_not_forced(self):
        result = converge_tags(
            ["hero", "cyberpunk city"],
            existing=["hero"],
            max_tags=8,
            force_existing=False,
        )
        assert result == ["hero", "cyberpunk city"]

    def test_new_words_still_keep_existing_spelling_on_casefold_match(self):
        result = converge_tags(
            ["HERO"],
            existing=["Hero"],
            max_tags=8,
            force_existing=False,
        )
        assert result == ["Hero"]

    def test_overlong_new_word_rejected_by_same_rule(self):
        result = converge_tags(
            ["x" * 201, "ok"],
            existing=[],
            max_tags=8,
            force_existing=False,
        )
        assert result == ["ok"]

    def test_whitespace_only_new_word_dropped(self):
        result = converge_tags(
            ["   ", ""],
            existing=[],
            max_tags=8,
            force_existing=False,
        )
        assert result == []

    def test_max_length_word_exactly_200_is_allowed(self):
        result = converge_tags(
            ["x" * 200], existing=[], max_tags=8, force_existing=False
        )
        assert result == ["x" * 200]


class TestDedupAndOrder:
    def test_exact_duplicates_dropped(self):
        result = converge_tags(
            ["hero", "hero", "hero"],
            existing=["hero"],
            max_tags=8,
            force_existing=True,
        )
        assert result == ["hero"]

    def test_casefold_duplicates_dropped_keeping_first_existing_spelling(self):
        result = converge_tags(
            ["hero", "HERO", "Hero"],
            existing=["hero"],
            max_tags=8,
            force_existing=True,
        )
        assert result == ["hero"]

    def test_model_confidence_order_preserved(self):
        result = converge_tags(
            ["c", "a", "b"],
            existing=["a", "b", "c"],
            max_tags=8,
            force_existing=True,
        )
        assert result == ["c", "a", "b"]

    def test_whitespace_stripped(self):
        result = converge_tags(
            ["  hero  "],
            existing=["hero"],
            max_tags=8,
            force_existing=True,
        )
        assert result == ["hero"]


class TestTruncation:
    def test_truncated_to_max_tags_in_order(self):
        result = converge_tags(
            ["a", "b", "c", "d"],
            existing=["a", "b", "c", "d"],
            max_tags=2,
            force_existing=True,
        )
        assert result == ["a", "b"]

    def test_new_words_count_toward_the_cap(self):
        result = converge_tags(
            ["a", "new1", "new2"],
            existing=["a"],
            max_tags=2,
            force_existing=False,
        )
        assert result == ["a", "new1"]

    def test_max_tags_zero_returns_empty(self):
        result = converge_tags(
            ["a"], existing=["a"], max_tags=0, force_existing=True
        )
        assert result == []


class TestDegenerateInputs:
    def test_empty_candidates(self):
        assert converge_tags([], existing=["a"], max_tags=8, force_existing=True) == []

    def test_non_string_candidates_dropped(self):
        result = converge_tags(
            [None, 42, "hero", ["nested"]],
            existing=["hero"],
            max_tags=8,
            force_existing=True,
        )
        assert result == ["hero"]

    def test_empty_everything(self):
        assert converge_tags([], existing=[], max_tags=8, force_existing=False) == []
