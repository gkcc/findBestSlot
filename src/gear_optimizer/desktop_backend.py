from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from gear_optimizer.desktop_protocol import (
    DesktopError,
    DesktopResponse,
    desktop_protocol_json_schema,
)
from gear_optimizer.desktop_service import DesktopService


def _configure_standard_streams() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local desktop backend over newline-delimited JSON."
    )
    parser.add_argument(
        "--root",
        help="Override the user-data root. Intended for tests and portable builds.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the desktop protocol JSON schema and exit.",
    )
    parser.add_argument("--request-file", help="Process one JSON request from a file.")
    parser.add_argument("--response-file", help="Write the one-shot response to a file.")
    return parser.parse_args(argv)


def _write_json_line(stream: TextIO, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    stream.flush()


def _invalid_json_response(message: str) -> DesktopResponse:
    return DesktopResponse(
        request_id="invalid-json",
        ok=False,
        error=DesktopError(code="invalid_json", message=message),
    )


def serve_stream(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    root: Path | None = None,
) -> int:
    service = DesktopService(root)
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            raw_request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _invalid_json_response(f"invalid JSON at column {exc.colno}: {exc.msg}")
            _write_json_line(output_stream, response.model_dump(mode="json"))
            continue
        response = service.execute_raw(raw_request)
        _write_json_line(output_stream, response.model_dump(mode="json"))
        if isinstance(raw_request, dict) and raw_request.get("method") == "system.shutdown":
            break
    return 0


def _run_one_shot(
    request_path: Path,
    response_path: Path | None,
    *,
    root: Path | None,
) -> int:
    service = DesktopService(root)
    try:
        raw_request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        response = _invalid_json_response(str(exc))
    else:
        response = service.execute_raw(raw_request)
    text = json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if response_path is None:
        print(text)
    else:
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(text + "\n", encoding="utf-8")
    return 0 if response.ok else 1


def main(argv: list[str] | None = None) -> int:
    _configure_standard_streams()
    args = parse_args(argv)
    root = Path(args.root).resolve() if args.root else None
    if args.schema:
        print(json.dumps(desktop_protocol_json_schema(), ensure_ascii=False, indent=2))
        return 0
    if args.response_file and not args.request_file:
        raise SystemExit("--response-file requires --request-file")
    if args.request_file:
        return _run_one_shot(
            Path(args.request_file),
            Path(args.response_file) if args.response_file else None,
            root=root,
        )
    return serve_stream(sys.stdin, sys.stdout, root=root)


if __name__ == "__main__":
    raise SystemExit(main())
