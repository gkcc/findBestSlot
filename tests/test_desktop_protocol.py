import pytest
from pydantic import ValidationError

from gear_optimizer.desktop_protocol import (
    DesktopError,
    DesktopRequest,
    DesktopResponse,
    UnsupportedDesktopProtocolVersionError,
    desktop_protocol_json_schema,
    parse_desktop_request,
)


def test_desktop_request_rejects_unknown_protocol_version():
    with pytest.raises(UnsupportedDesktopProtocolVersionError):
        parse_desktop_request(
            {
                "schema_version": 2,
                "request_id": "request-1",
                "method": "system.ping",
            }
        )


def test_desktop_protocol_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        DesktopRequest.model_validate(
            {
                "request_id": "request-1",
                "method": "system.ping",
                "unexpected": True,
            }
        )


def test_desktop_response_requires_error_for_failure():
    with pytest.raises(ValidationError):
        DesktopResponse(request_id="request-1", ok=False)

    response = DesktopResponse(
        request_id="request-1",
        ok=False,
        error=DesktopError(code="invalid", message="invalid request"),
    )

    assert response.error is not None
    assert response.error.code == "invalid"


def test_desktop_protocol_schema_exports_all_wire_models():
    schema = desktop_protocol_json_schema()

    assert schema["schema_version"] == 1
    assert set(schema) == {"schema_version", "request", "response", "event", "workspace"}
