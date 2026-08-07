"""Translation integrity tests."""

import json
from pathlib import Path

TRANSLATIONS = (
    Path(__file__).parents[1] / "custom_components" / "torrserver" / "translations"
)


def _leaf_keys(value, prefix=""):
    keys = set()
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            keys.update(_leaf_keys(item, path))
        else:
            keys.add(path)
    return keys


def test_translation_files_are_valid_and_have_matching_keys():
    documents = {
        language: json.loads((TRANSLATIONS / f"{language}.json").read_text("utf-8"))
        for language in ("en", "it", "ru")
    }

    expected = _leaf_keys(documents["en"])
    assert _leaf_keys(documents["it"]) == expected
    assert _leaf_keys(documents["ru"]) == expected
