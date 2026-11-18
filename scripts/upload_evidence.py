"""Upload an image through the OfferTrap backend into Neon Object Storage."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPPORTED_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
DEFAULT_API_BASE = "http://localhost:8000/api/v1"


class UploadScriptError(Exception):
    """An actionable failure while calling the backend API."""


def _decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace").strip()


def _response_error(error: HTTPError, path: str) -> UploadScriptError:
    detail = _decode_body(error.read())
    message = f"Backend returned HTTP {error.code} for {path}."
    if detail:
        message += f" Response: {detail}"
    return UploadScriptError(message)


def _post_json(
    api_base: str, path: str, payload: dict[str, Any], timeout: int
) -> dict[str, Any]:
    request = Request(
        f"{api_base.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = _decode_body(response.read())
    except HTTPError as error:
        raise _response_error(error, path) from None
    except URLError as error:
        raise UploadScriptError(f"Could not reach the backend at {api_base}: {error.reason}") from None

    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        raise UploadScriptError(f"Backend returned a non-JSON response for {path}.") from None
    if not isinstance(result, dict):
        raise UploadScriptError(f"Backend returned an unexpected response for {path}.")
    return result


def _put_chunk(api_base: str, upload_id: str, index: int, data: bytes, timeout: int) -> None:
    path = f"/uploads/{upload_id}/chunks/{index}"
    request = Request(
        f"{api_base.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/octet-stream"},
        method="PUT",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
    except HTTPError as error:
        raise _response_error(error, path) from None
    except URLError as error:
        raise UploadScriptError(f"Could not upload chunk {index}: {error.reason}") from None


def _ask(prompt: str, *, optional: bool = False) -> str | None:
    value = input(prompt).strip()
    return value or None if optional else value


def _ask_yes_no(prompt: str) -> bool:
    return input(prompt).strip().lower() in {"y", "yes"}


def _prompt_report() -> dict[str, Any]:
    print("\nReport details (this creates a real report in the configured database):")
    return {
        "contributor_username": _ask("Your display name: "),
        "contributor_email": _ask("Your email (private): "),
        "anonymous_attribution": _ask_yes_no("Publish your name anonymously? [y/N]: "),
        "company_name": _ask("Company or organization: "),
        "recruiter_contact": _ask("Recruiter mobile (optional, 10 digits): ", optional=True),
        "job_title": _ask("Job title (optional): ", optional=True),
        "job_url": _ask("Job posting URL (optional): ", optional=True),
        "category": _ask("Incident category [Advance-fee recruitment]: ")
        or "Advance-fee recruitment",
        "description": _ask("Incident description (at least 20 characters): "),
        "payment_requested": _ask_yes_no("Was payment requested? [y/N]: "),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload one image through the backend into Neon Object Storage."
    )
    parser.add_argument("file", type=Path, help="JPEG, PNG, or WEBP evidence image.")
    parser.add_argument(
        "--api-base",
        default=os.getenv("OFFERTRAP_API_BASE", DEFAULT_API_BASE),
        help=(
            "Backend API base ending in /api/v1. Defaults to OFFERTRAP_API_BASE "
            f"or {DEFAULT_API_BASE}."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds for each backend request (default: 120).",
    )
    parser.add_argument(
        "--submit-report",
        action="store_true",
        help="Prompt for report fields and create the report after its image is stored.",
    )
    args = parser.parse_args()

    file_path = args.file.expanduser()
    if not file_path.is_file():
        raise UploadScriptError(f"File not found: {file_path}")
    content_type = SUPPORTED_TYPES.get(file_path.suffix.lower())
    if not content_type:
        supported = ", ".join(SUPPORTED_TYPES)
        raise UploadScriptError(f"Unsupported image extension. Use one of: {supported}.")
    file_size = file_path.stat().st_size
    if file_size <= 0:
        raise UploadScriptError("The selected file is empty.")
    if args.timeout < 1:
        raise UploadScriptError("--timeout must be a positive number of seconds.")

    report = _prompt_report() if args.submit_report else None
    print(f"Starting a backend upload for {file_path.name} ({file_size:,} bytes)...")
    upload = _post_json(
        args.api_base,
        "/uploads",
        {
            "filename": file_path.name,
            "content_type": content_type,
            "size_bytes": file_size,
        },
        args.timeout,
    )
    upload_id = upload.get("upload_id")
    chunk_size = upload.get("chunk_size_bytes")
    chunk_count = upload.get("chunk_count")
    if (
        not isinstance(upload_id, str)
        or not upload_id
        or not isinstance(chunk_size, int)
        or chunk_size < 1
        or not isinstance(chunk_count, int)
        or chunk_count < 1
    ):
        raise UploadScriptError("The backend returned an invalid upload manifest.")

    with file_path.open("rb") as evidence_file:
        for chunk_index in range(chunk_count):
            chunk = evidence_file.read(chunk_size)
            if not chunk:
                raise UploadScriptError("The local image ended before all chunks were sent.")
            _put_chunk(args.api_base, upload_id, chunk_index, chunk, args.timeout)
            print(f"Uploaded chunk {chunk_index + 1} of {chunk_count}.")
        if evidence_file.read(1):
            raise UploadScriptError("The local image changed while it was being uploaded.")

    _post_json(args.api_base, f"/uploads/{upload_id}/complete", {}, args.timeout)
    print("Image upload succeeded and is stored in Neon Object Storage.")
    print(f"Pending upload ID: {upload_id}")

    if report is None:
        print("No report was created. Use --submit-report for an end-to-end submission.")
        return 0

    report["evidence_upload_ids"] = [upload_id]
    result = _post_json(args.api_base, "/reports", report, args.timeout)
    print("Report submission succeeded.")
    print(f"Report ID: {result.get('id', '(no ID returned)')}")
    print(f"Status: {result.get('status', '(no status returned)')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UploadScriptError as error:
        print(f"Upload failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Upload cancelled.", file=sys.stderr)
        raise SystemExit(130) from None
