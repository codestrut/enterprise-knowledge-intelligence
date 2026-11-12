#!/usr/bin/env python3
"""Loopback-only in-memory API mock for the EKIP Task 06 browser smoke test.

This server is test-only. It does not import EKIP application code, connect to a
real database, read credentials, write files, or contact external services.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

HOST = "127.0.0.1"
PORT = 8003

ORGANISATIONS: list[dict[str, object]] = [
    {
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "Synthetic Pending Institute",
        "slug": "synthetic-pending",
        "is_active": False,
        "status": "registration_pending",
        "initial_admin_email": "pending-admin@example.test",
        "provisioning_attempts": 0,
        "provisioning_started_at": None,
        "provisioning_error_code": None,
        "created_at": "2026-10-20T12:00:00+00:00",
    },
    {
        "id": "22222222-2222-4222-8222-222222222222",
        "name": "Synthetic Stale Institute",
        "slug": "synthetic-stale",
        "is_active": False,
        "status": "provisioning",
        "initial_admin_email": "stale-admin@example.test",
        "provisioning_attempts": 1,
        "provisioning_started_at": "2026-10-23T08:00:00+00:00",
        "provisioning_error_code": None,
        "created_at": "2026-10-21T12:00:00+00:00",
    },
    {
        "id": "33333333-3333-4333-8333-333333333333",
        "name": "Synthetic Failed Institute",
        "slug": "synthetic-failed",
        "is_active": False,
        "status": "provisioning_failed",
        "initial_admin_email": "failed-admin@example.test",
        "provisioning_attempts": 2,
        "provisioning_started_at": None,
        "provisioning_error_code": "workspace_timeout",
        "created_at": "2026-10-22T12:00:00+00:00",
    },
]

USERS = [
    {
        "id": "44444444-4444-4444-8444-444444444444",
        "email": "owner@example.test",
        "is_active": True,
    }
]
ROLE_ASSIGNMENTS: set[tuple[str, str]] = set()
IDEMPOTENCY_KEYS: dict[str, str] = {}

PLATFORM_PERMISSIONS = [
    "organisations:read",
    "organisations:create",
    "organisations:approve",
    "organisations:provisioning-retry",
    "organisations:provisioning-recover",
    "platform-roles:assign",
    "platform-users:manage",
    "platform-audit:read",
]


def response(handler: BaseHTTPRequestHandler, status: int, body: object) -> None:
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


class SmokeMockHandler(BaseHTTPRequestHandler):
    server_version = "EKIP-Task06-Smoke-Mock/1.0"

    def log_message(self, format_string: str, *args: object) -> None:
        # Log only method and route; never log request bodies or headers.
        print(f"[task06-smoke-mock] {self.command} {urlparse(self.path).path}", flush=True)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            return response(self, 200, {
                "status": "ok",
                "document_count": 0,
                "chunk_count": 0,
                "manifest_exists": False,
                "failed_document_count": 0,
            })
        if path == "/documents":
            return response(self, 200, {"count": 0, "documents": []})
        if path == "/auth/me":
            return response(self, 200, {
                "email": "platform-operator@example.test",
                "organisation": {
                    "id": "55555555-5555-4555-8555-555555555555",
                    "name": "Synthetic Platform Operations",
                },
                "role": "organisation_administrator",
                "permissions": ["documents:read", "documents:query"],
                "platform_permissions": PLATFORM_PERMISSIONS,
            })
        if path == "/platform/organisations":
            return response(self, 200, {
                "count": len(ORGANISATIONS),
                "organisations": ORGANISATIONS,
            })
        if path == "/platform/users":
            query = parse_qs(parsed.query).get("q", [""])[0].strip().lower()
            limit_raw = parse_qs(parsed.query).get("limit", ["25"])[0]
            try:
                limit = max(1, min(50, int(limit_raw)))
            except ValueError:
                return response(self, 422, {"detail": "Invalid limit."})
            matches = [user for user in USERS if query in str(user["email"]).lower()]
            return response(self, 200, {"count": len(matches[:limit]), "users": matches[:limit]})
        return response(self, 404, {"detail": "Synthetic smoke API route not found."})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler method name
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            raw_length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(raw_length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object.")
        except (ValueError, json.JSONDecodeError):
            return response(self, 400, {"detail": "A JSON object is required."})

        if path == "/platform/organisations":
            key = self.headers.get("Idempotency-Key", "").strip()
            name = str(body.get("name", "")).strip()
            slug = str(body.get("slug", "")).strip().lower()
            email = str(body.get("initial_admin_email", "")).strip().lower()
            if not key or not name or not slug or "@" not in email:
                return response(self, 422, {"detail": "A valid idempotency key and organisation fields are required."})
            if key in IDEMPOTENCY_KEYS:
                org_id = IDEMPOTENCY_KEYS[key]
                existing = next(org for org in ORGANISATIONS if org["id"] == org_id)
                return response(self, 201, {
                    "organisation_id": existing["id"], "name": existing["name"],
                    "slug": existing["slug"], "status": existing["status"],
                    "initial_admin_email": existing["initial_admin_email"],
                    "provisioning_attempts": existing["provisioning_attempts"],
                    "idempotent_replay": True, "normal_access_enabled": False,
                    "request_id": str(uuid4()),
                })
            org_id = str(uuid4())
            organisation: dict[str, object] = {
                "id": org_id, "name": name, "slug": slug, "is_active": False,
                "status": "registration_pending", "initial_admin_email": email,
                "provisioning_attempts": 0, "provisioning_started_at": None,
                "provisioning_error_code": None, "created_at": "2026-10-23T12:00:00+00:00",
            }
            ORGANISATIONS.insert(0, organisation)
            IDEMPOTENCY_KEYS[key] = org_id
            return response(self, 201, {
                "organisation_id": org_id, "name": name, "slug": slug,
                "status": "registration_pending", "initial_admin_email": email,
                "provisioning_attempts": 0, "idempotent_replay": False,
                "normal_access_enabled": False, "request_id": str(uuid4()),
            })

        if path == "/platform/users/roles":
            user_id = str(body.get("user_id", ""))
            role = str(body.get("role", ""))
            user_exists = any(user["id"] == user_id for user in USERS)
            valid_roles = {
                "platform_tenant_creator", "platform_tenant_approver",
                "platform_provisioning_operator", "platform_super_administrator",
            }
            if not user_exists:
                return response(self, 404, {"detail": "Synthetic user not found."})
            if role not in valid_roles:
                return response(self, 422, {"detail": "Invalid platform role."})
            assignment = (user_id, role)
            already_assigned = assignment in ROLE_ASSIGNMENTS
            ROLE_ASSIGNMENTS.add(assignment)
            return response(self, 201, {
                "user_id": user_id, "role": role, "already_assigned": already_assigned,
            })

        match = None
        for action_suffix, new_status in (
            ("/approve-provisioning", "pending_admin"),
            ("/provisioning/retry", "pending_admin"),
            ("/provisioning/recover", "provisioning_failed"),
        ):
            if path.startswith("/platform/organisations/") and path.endswith(action_suffix):
                match = (path[len("/platform/organisations/"):-len(action_suffix)], action_suffix, new_status)
                break
        if match is not None:
            org_id, action_suffix, new_status = match
            organisation = next((org for org in ORGANISATIONS if org["id"] == org_id), None)
            if organisation is None:
                return response(self, 404, {"detail": "Synthetic organisation not found."})
            if not str(body.get("approval_reason", body.get("reason", ""))).strip():
                return response(self, 422, {"detail": "A reason is required."})
            if action_suffix == "/approve-provisioning" and organisation["status"] != "registration_pending":
                return response(self, 409, {"detail": "Organisation is not pending approval."})
            if action_suffix == "/provisioning/recover" and organisation["status"] != "provisioning":
                return response(self, 409, {"detail": "Organisation is not provisioning."})
            if action_suffix == "/provisioning/retry":
                if organisation["status"] != "provisioning_failed" or int(organisation["provisioning_attempts"]) >= 5:
                    return response(self, 409, {"detail": "Organisation is not eligible for retry."})
                organisation["provisioning_attempts"] = int(organisation["provisioning_attempts"]) + 1
            if action_suffix == "/provisioning/recover":
                organisation["provisioning_error_code"] = "stale_attempt_recovered"
                organisation["provisioning_started_at"] = None
            if action_suffix == "/approve-provisioning":
                organisation["provisioning_attempts"] = max(1, int(organisation["provisioning_attempts"]))
            organisation["status"] = new_status
            organisation["is_active"] = False
            if new_status == "pending_admin":
                organisation["provisioning_error_code"] = None
                organisation["provisioning_started_at"] = None
            return response(self, 200, {
                "organisation_id": org_id, "status": new_status,
                "provisioning_attempts": organisation["provisioning_attempts"],
                "normal_access_enabled": False,
            })

        return response(self, 404, {"detail": "Synthetic smoke API route not found."})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler method name
        parsed = urlparse(self.path)
        body = b"ok" if parsed.path == "/health" else b""
        self.send_response(200 if parsed.path == "/health" else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), SmokeMockHandler)
    print(f"EKIP Task 06 in-memory smoke mock listening only on http://{HOST}:{PORT}", flush=True)
    print("Synthetic data only: no production API, database, credentials, or tenant storage.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
