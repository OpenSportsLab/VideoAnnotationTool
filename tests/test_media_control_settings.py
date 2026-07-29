import pytest
from PyQt6.QtCore import QSettings

from media_control_settings import (
    DEFAULT_PLAYBACK_FACTORS,
    DEFAULT_SEEK_INTERVALS,
    PLAYBACK_FACTORS_KEY,
    SEEK_INTERVALS_KEY,
    load_media_control_settings,
    parse_playback_factors,
    parse_seek_intervals,
)


@pytest.mark.parametrize(
    ("text", "normalized", "rates"),
    [
        ("2", "2", (0.5, 1.0, 2.0)),
        (" 4, 2, 4 ", "2,4", (0.25, 0.5, 1.0, 2.0, 4.0)),
        ("2,4,8", "2,4,8", (0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)),
        ("3", "3", (0.333, 1.0, 3.0)),
        ("0.5", "0.5", (0.5, 1.0, 2.0)),
    ],
)
def test_parse_playback_factors(text, normalized, rates):
    parsed = parse_playback_factors(text)
    assert parsed.normalized_text == normalized
    assert parsed.values == rates


def test_parse_seek_intervals_normalizes_decimals_order_and_duplicates():
    parsed = parse_seek_intervals(" 5, 1, 0.250, 1 ")
    assert parsed.normalized_text == "0.25,1,5"
    assert parsed.values == (0.25, 1.0, 5.0)


@pytest.mark.parametrize(
    "parser,text",
    [
        (parse_playback_factors, ""),
        (parse_playback_factors, "2,"),
        (parse_playback_factors, "abc"),
        (parse_playback_factors, "0"),
        (parse_playback_factors, "-2"),
        (parse_playback_factors, "NaN"),
        (parse_playback_factors, "Infinity"),
        (parse_playback_factors, "1000000"),
        (parse_seek_intervals, "0.0001"),
    ],
)
def test_media_control_parsers_reject_invalid_values(parser, text):
    with pytest.raises(ValueError):
        parser(text)


def test_load_media_control_settings_falls_back_independently(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue(PLAYBACK_FACTORS_KEY, "invalid")
    settings.setValue(SEEK_INTERVALS_KEY, "1,10")

    factors, intervals = load_media_control_settings(settings)

    assert factors.normalized_text == DEFAULT_PLAYBACK_FACTORS
    assert intervals.normalized_text == "1,10"
    assert DEFAULT_SEEK_INTERVALS == "1,5"


def test_media_control_settings_survive_qsettings_recreation(tmp_path):
    path = str(tmp_path / "settings.ini")
    settings = QSettings(path, QSettings.Format.IniFormat)
    settings.setValue(PLAYBACK_FACTORS_KEY, "2,4,8")
    settings.setValue(SEEK_INTERVALS_KEY, "1,5,10")
    settings.sync()

    recreated = QSettings(path, QSettings.Format.IniFormat)
    factors, intervals = load_media_control_settings(recreated)

    assert factors.normalized_text == "2,4,8"
    assert intervals.normalized_text == "1,5,10"
