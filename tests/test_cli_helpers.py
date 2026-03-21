from glamtool.cli import build_filter, extract_artist_song, format_datetime_for_sheet


def test_build_filter_combines_structured_filters():
    result = build_filter(
        published_only=True,
        missing_images_only=True,
        tags=[" song-pick ", "2026"],
        any_tag=False,
        raw_filter='title:~"London"',
    )

    assert (
        result
        == 'status:published+feature_image:null+tag:song-pick+tag:2026+title:~"London"'
    )


def test_build_filter_uses_any_tag_syntax_for_multiple_tags():
    result = build_filter(
        published_only=False,
        missing_images_only=False,
        tags=["song-pick", "review"],
        any_tag=True,
        raw_filter=None,
    )

    assert result == "tag:[song-pick,review]"


def test_build_filter_returns_none_when_nothing_selected():
    assert build_filter(False, False, None, False, None) is None


def test_format_datetime_for_sheet_normalizes_utc_suffix():
    assert format_datetime_for_sheet("2026-02-27T13:45:09Z") == "2026-02-27 13:45:09"


def test_format_datetime_for_sheet_preserves_unparseable_values():
    assert format_datetime_for_sheet("not-a-date") == "not-a-date"


def test_extract_artist_song_supports_prefix_and_suffix_cleanup():
    assert extract_artist_song("SONG PICK: MUNA - Number One Fan [VIDEO]") == (
        "MUNA",
        "Number One Fan",
    )


def test_extract_artist_song_handles_unicode_space_cleanup():
    title = "Beyonce\u00a0-\u200b CUFF IT"

    assert extract_artist_song(title) == ("Beyonce", "CUFF IT")


def test_extract_artist_song_returns_empty_fields_for_non_matching_titles():
    assert extract_artist_song("Just a title") == ("", "")
