import json

import pytest

from scripts.smoke_packaged_backend import _parse_response


def test_parse_packaged_backend_response_accepts_one_unicode_ndjson_line():
    request_id = "tauri-package-smoke-\u2022"
    stdout = json.dumps(
        {
            "schema_version": 1,
            "request_id": request_id,
            "ok": True,
            "data": {"workspace": {"game_name": "\u7edd\u533a\u96f6"}},
        },
        ensure_ascii=False,
    )

    response = _parse_response(stdout + "\n", request_id)

    assert response["data"]["workspace"]["game_name"] == "\u7edd\u533a\u96f6"


@pytest.mark.parametrize(
    "stdout, message",
    [
        ("", "expected one NDJSON response line"),
        ("{}\n{}\n", "expected one NDJSON response line"),
        (
            json.dumps({"request_id": "wrong", "ok": True, "data": {"workspace": {}}}),
            "request_id does not match",
        ),
        (
            json.dumps(
                {
                    "request_id": "expected",
                    "ok": False,
                    "error": {"code": "internal_error"},
                }
            ),
            "NDJSON backend error",
        ),
    ],
)
def test_parse_packaged_backend_response_rejects_invalid_stream(stdout, message):
    with pytest.raises(ValueError, match=message):
        _parse_response(stdout, "expected")
