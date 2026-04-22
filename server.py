from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import secrets
import base64
import threading
import uuid
from datetime import UTC, date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
STORE_PATH = Path(os.environ.get("UTOWN_STORE_PATH", str(BASE_DIR / "data" / "store.json"))).resolve()

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

DEFAULT_OWNER_LOGIN_ID = os.environ.get("UTOWN_OWNER_ID", "owner")
DEFAULT_OWNER_PASSWORD = os.environ.get(
    "UTOWN_OWNER_PASSWORD",
    os.environ.get("UTOWN_ADMIN_PASSWORD", "utown-admin"),
)
APP_TIMEZONE = os.environ.get("UTOWN_TIMEZONE", "UTC")

ACTIVE_REQUEST_STATUSES = {"pending", "approved"}
LOGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")


class ValidationError(Exception):
    """Raised when a request breaks a business rule."""


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_today_iso() -> str:
    try:
        timezone = ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        timezone = UTC
    return datetime.now(timezone).date().isoformat()


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${base64.b64encode(salt).decode('ascii')}${base64.b64encode(derived_key).decode('ascii')}"


def verify_secret(secret: str, stored_hash: str) -> bool:
    if stored_hash.startswith("scrypt$"):
        _, salt_b64, derived_key_b64 = stored_hash.split("$", 2)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected_key = base64.b64decode(derived_key_b64.encode("ascii"))
        candidate_key = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return secrets.compare_digest(candidate_key, expected_key)

    return secrets.compare_digest(stored_hash, hashlib.sha256(secret.encode("utf-8")).hexdigest())


def normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def normalize_login_id(login_id: str) -> str:
    clean_login_id = login_id.strip()
    if not LOGIN_ID_PATTERN.fullmatch(clean_login_id):
        raise ValidationError(
            "Login ID must be 3-32 characters and can use letters, numbers, dots, underscores, and dashes."
        )
    return clean_login_id


def validate_password(password: str, label: str = "Password") -> str:
    clean_password = password.strip()
    if len(clean_password) < 6:
        raise ValidationError(f"{label} must be at least 6 characters.")
    return clean_password


def generate_password(prefix: str = "UT") -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    token = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{prefix}-{token}"


class LeaveTrackerStore:
    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.lock = threading.Lock()
        self._ensure_store()

    def _default_payload(self) -> dict:
        return {
            "schemaVersion": 2,
            "company": "UTown",
            "owner": {
                "loginId": DEFAULT_OWNER_LOGIN_ID,
                "passwordHash": hash_secret(DEFAULT_OWNER_PASSWORD),
                "updatedAt": utc_timestamp(),
            },
            "employees": [],
            "requests": [],
        }

    def _ensure_store(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write(self._default_payload())
            return

        payload = self._read()
        migrated_payload, changed = self._migrate_payload(payload)
        if changed:
            self._write(migrated_payload)

    def _migrate_payload(self, payload: dict) -> tuple[dict, bool]:
        changed = False
        default_payload = self._default_payload()

        if payload.get("schemaVersion") != 2:
            payload["schemaVersion"] = 2
            changed = True

        if "company" not in payload:
            payload["company"] = default_payload["company"]
            changed = True

        if "owner" not in payload or not isinstance(payload["owner"], dict):
            payload["owner"] = default_payload["owner"]
            changed = True
        else:
            owner = payload["owner"]
            if "loginId" not in owner:
                owner["loginId"] = DEFAULT_OWNER_LOGIN_ID
                changed = True
            if "passwordHash" not in owner:
                owner["passwordHash"] = hash_secret(DEFAULT_OWNER_PASSWORD)
                changed = True
            if "updatedAt" not in owner:
                owner["updatedAt"] = utc_timestamp()
                changed = True

        if "employees" not in payload or not isinstance(payload["employees"], list):
            payload["employees"] = []
            changed = True

        if "requests" not in payload:
            requests = []
            for legacy_leave in payload.get("leaves", []):
                requests.append(
                    {
                        "id": f"req-{uuid.uuid4().hex[:10]}",
                        "employeeId": legacy_leave["employeeId"],
                        "date": legacy_leave["date"],
                        "status": "approved",
                        "updatedAt": legacy_leave.get("updatedAt", utc_timestamp()),
                        "decisionAt": legacy_leave.get("updatedAt", utc_timestamp()),
                    }
                )
            payload["requests"] = requests
            changed = True

        if "leaves" in payload:
            payload.pop("leaves")
            changed = True

        highest_numeric_login = 0
        for employee in payload["employees"]:
            login_id = employee.get("loginId", "")
            if re.fullmatch(r"UT(\d+)", login_id):
                highest_numeric_login = max(highest_numeric_login, int(login_id[2:]))

        next_login_number = highest_numeric_login + 1

        for employee in payload["employees"]:
            if "id" not in employee:
                employee["id"] = f"emp-{uuid.uuid4().hex[:10]}"
                changed = True

            if "name" in employee:
                normalized = normalize_name(employee["name"])
                if normalized != employee["name"]:
                    employee["name"] = normalized
                    changed = True

            if "passwordHash" not in employee:
                if "pinHash" in employee:
                    employee["passwordHash"] = employee["pinHash"]
                else:
                    employee["passwordHash"] = hash_secret(generate_password("TEMP"))
                changed = True

            if "pinHash" in employee:
                employee.pop("pinHash")
                changed = True

            if "loginId" not in employee:
                employee["loginId"] = f"UT{next_login_number:03d}"
                next_login_number += 1
                changed = True

            if "active" not in employee:
                employee["active"] = True
                changed = True

            if "createdAt" not in employee:
                employee["createdAt"] = utc_timestamp()
                changed = True

        normalized_requests = []
        for request in payload["requests"]:
            normalized_request = dict(request)
            if "id" not in normalized_request:
                normalized_request["id"] = f"req-{uuid.uuid4().hex[:10]}"
                changed = True
            if "status" not in normalized_request:
                normalized_request["status"] = "approved"
                changed = True
            if "updatedAt" not in normalized_request:
                normalized_request["updatedAt"] = utc_timestamp()
                changed = True
            if normalized_request.get("status") in {"approved", "rejected"} and "decisionAt" not in normalized_request:
                normalized_request["decisionAt"] = normalized_request["updatedAt"]
                changed = True
            normalized_requests.append(normalized_request)

        payload["requests"] = normalized_requests

        return payload, changed

    def _read(self) -> dict:
        with self.store_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict) -> None:
        temp_path = self.store_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        temp_path.replace(self.store_path)

    def owner_login_id(self) -> str:
        with self.lock:
            payload = self._read()
            return payload["owner"]["loginId"]

    def owner_uses_default_credentials(self) -> bool:
        with self.lock:
            payload = self._read()
            owner = payload["owner"]
            return owner["loginId"] == DEFAULT_OWNER_LOGIN_ID and verify_secret(
                DEFAULT_OWNER_PASSWORD,
                owner["passwordHash"],
            )

    def verify_admin(self, login_id: str, password: str) -> bool:
        with self.lock:
            payload = self._read()
            owner = payload["owner"]
            effective_login_id = login_id.strip() or owner["loginId"]
            if not password:
                return False
            return secrets.compare_digest(owner["loginId"], effective_login_id) and verify_secret(
                password,
                owner["passwordHash"],
            )

    def public_snapshot(self) -> dict:
        with self.lock:
            payload = self._read()
            requests = [self._serialize_request(payload, request) for request in payload["requests"]]
            active_requests = [request for request in requests if request["status"] in ACTIVE_REQUEST_STATUSES]
            active_requests.sort(key=lambda request: (request["date"], request["employeeName"].lower()))

            return {
                "company": payload.get("company", "UTown"),
                "today": local_today_iso(),
                "ownerLoginId": payload["owner"]["loginId"],
                "employeeCount": sum(1 for employee in payload["employees"] if employee.get("active", True)),
                "requests": active_requests,
                "rules": {
                    "singleLeavePerMonth": True,
                    "weekdaysOnly": True,
                    "singleEmployeePerDay": True,
                    "ownerApprovalRequired": True,
                },
            }

    def admin_snapshot(self) -> dict:
        with self.lock:
            payload = self._read()

            employees = [
                {
                    "id": employee["id"],
                    "loginId": employee["loginId"],
                    "name": employee["name"],
                    "active": employee.get("active", True),
                    "createdAt": employee.get("createdAt"),
                }
                for employee in payload["employees"]
            ]
            employees.sort(key=lambda employee: (employee["name"].lower(), employee["loginId"]))

            requests = [self._serialize_request(payload, request, include_login_id=True) for request in payload["requests"]]
            requests.sort(
                key=lambda request: (
                    request["status"] != "pending",
                    request["date"],
                    request["employeeName"].lower(),
                )
            )

            return {
                "company": payload.get("company", "UTown"),
                "today": local_today_iso(),
                "ownerLoginId": payload["owner"]["loginId"],
                "employees": employees,
                "requests": requests,
            }

    def employee_session(self, login_id: str, password: str) -> dict:
        with self.lock:
            payload = self._read()
            employee = self._require_active_employee_by_login(payload, login_id, password)
            requests = [
                self._serialize_request(payload, request)
                for request in payload["requests"]
                if request["employeeId"] == employee["id"]
            ]
            requests.sort(key=lambda request: request["date"])

            return {
                "employee": {
                    "id": employee["id"],
                    "loginId": employee["loginId"],
                    "name": employee["name"],
                    "active": employee.get("active", True),
                },
                "requests": requests,
            }

    def add_employee(self, name: str, password: str) -> dict:
        clean_name = normalize_name(name)
        provided_password = password.strip()
        employee_password = validate_password(provided_password, "Employee password") if provided_password else generate_password("EMP")

        if not clean_name:
            raise ValidationError("Enter an employee name.")

        with self.lock:
            payload = self._read()
            for employee in payload["employees"]:
                if employee["name"].lower() == clean_name.lower():
                    raise ValidationError("An employee with that name already exists.")

            employee_id = f"emp-{uuid.uuid4().hex[:10]}"
            login_id = self._next_employee_login_id(payload)
            payload["employees"].append(
                {
                    "id": employee_id,
                    "loginId": login_id,
                    "name": clean_name,
                    "active": True,
                    "passwordHash": hash_secret(employee_password),
                    "createdAt": utc_timestamp(),
                }
            )
            self._write(payload)

        return {
            "employeeId": employee_id,
            "loginId": login_id,
            "name": clean_name,
            "password": employee_password,
        }

    def set_employee_status(self, employee_id: str, active: bool) -> dict:
        with self.lock:
            payload = self._read()
            employee = self._require_employee(payload, employee_id)
            employee["active"] = bool(active)
            self._write(payload)

        return {"employeeId": employee_id, "active": bool(active)}

    def reset_employee_password(self, employee_id: str, password: str) -> dict:
        clean_password = password.strip()
        next_password = (
            validate_password(clean_password, "Employee password") if clean_password else generate_password("EMP")
        )

        with self.lock:
            payload = self._read()
            employee = self._require_employee(payload, employee_id)
            employee["passwordHash"] = hash_secret(next_password)
            self._write(payload)

        return {
            "employeeId": employee_id,
            "loginId": employee["loginId"],
            "name": employee["name"],
            "password": next_password,
        }

    def update_owner_credentials(self, login_id: str, password: str) -> dict:
        clean_login_id = normalize_login_id(login_id)
        clean_password = validate_password(password, "Owner password")

        with self.lock:
            payload = self._read()
            payload["owner"]["loginId"] = clean_login_id
            payload["owner"]["passwordHash"] = hash_secret(clean_password)
            payload["owner"]["updatedAt"] = utc_timestamp()
            self._write(payload)

        return {"ownerLoginId": clean_login_id}

    def submit_employee_request(self, login_id: str, password: str, request_date: str) -> dict:
        with self.lock:
            payload = self._read()
            employee = self._require_active_employee_by_login(payload, login_id, password)
            requested_day = self._validate_request_date(payload, employee["id"], request_date)

            matching_request = self._find_employee_month_request(payload, employee["id"], requested_day)
            now = utc_timestamp()

            if matching_request:
                if matching_request["date"] == request_date and matching_request.get("status") == "pending":
                    action = "unchanged"
                else:
                    matching_request["date"] = request_date
                    matching_request["status"] = "pending"
                    matching_request["updatedAt"] = now
                    matching_request["decisionAt"] = None
                    action = "updated"
            else:
                matching_request = {
                    "id": f"req-{uuid.uuid4().hex[:10]}",
                    "employeeId": employee["id"],
                    "date": request_date,
                    "status": "pending",
                    "updatedAt": now,
                    "decisionAt": None,
                }
                payload["requests"].append(matching_request)
                action = "created"

            self._write(payload)

        return {
            "requestId": matching_request["id"],
            "employeeName": employee["name"],
            "date": request_date,
            "status": "pending",
            "action": action,
        }

    def cancel_employee_request(self, login_id: str, password: str, request_id: str) -> dict:
        with self.lock:
            payload = self._read()
            employee = self._require_active_employee_by_login(payload, login_id, password)
            request = self._require_request(payload, request_id)

            if request["employeeId"] != employee["id"]:
                raise ValidationError("That request does not belong to this employee.")

            payload["requests"] = [entry for entry in payload["requests"] if entry["id"] != request_id]
            self._write(payload)

        return {"requestId": request_id, "cancelled": True}

    def review_request(self, request_id: str, action: str) -> dict:
        normalized_action = action.strip().lower()
        if normalized_action not in {"approve", "reject"}:
            raise ValidationError("Choose approve or reject.")

        with self.lock:
            payload = self._read()
            request = self._require_request(payload, request_id)
            employee = self._require_employee(payload, request["employeeId"])

            if normalized_action == "approve":
                self._validate_request_date(payload, employee["id"], request["date"], ignore_request_id=request_id)
                request["status"] = "approved"
            else:
                request["status"] = "rejected"

            request["decisionAt"] = utc_timestamp()
            request["updatedAt"] = request["decisionAt"]
            self._write(payload)

            return self._serialize_request(payload, request, include_login_id=True)

    def _serialize_request(self, payload: dict, request: dict, include_login_id: bool = False) -> dict:
        employee = self._employee_by_id(payload, request["employeeId"])
        serialized = {
            "id": request["id"],
            "employeeId": request["employeeId"],
            "employeeName": employee["name"] if employee else "Unknown employee",
            "date": request["date"],
            "status": request.get("status", "pending"),
            "updatedAt": request.get("updatedAt"),
            "decisionAt": request.get("decisionAt"),
        }
        if include_login_id and employee:
            serialized["employeeLoginId"] = employee["loginId"]
        return serialized

    def _next_employee_login_id(self, payload: dict) -> str:
        highest = 0
        for employee in payload["employees"]:
            match = re.fullmatch(r"UT(\d+)", employee.get("loginId", ""))
            if match:
                highest = max(highest, int(match.group(1)))
        return f"UT{highest + 1:03d}"

    def _employee_by_id(self, payload: dict, employee_id: str) -> dict | None:
        for employee in payload["employees"]:
            if employee["id"] == employee_id:
                return employee
        return None

    def _employee_by_login(self, payload: dict, login_id: str) -> dict | None:
        for employee in payload["employees"]:
            if employee["loginId"].lower() == login_id.lower().strip():
                return employee
        return None

    def _require_employee(self, payload: dict, employee_id: str) -> dict:
        employee = self._employee_by_id(payload, employee_id)
        if not employee:
            raise ValidationError("Employee not found.")
        return employee

    def _require_employee_password(self, employee: dict, password: str) -> None:
        if not password:
            raise ValidationError("Enter the employee password.")
        if not verify_secret(password, employee["passwordHash"]):
            raise ValidationError("The employee ID or password is incorrect.")

    def _require_active_employee_by_login(self, payload: dict, login_id: str, password: str) -> dict:
        employee = self._employee_by_login(payload, login_id)
        if not employee:
            raise ValidationError("The employee ID or password is incorrect.")
        if not employee.get("active", True):
            raise ValidationError("This employee is inactive. Ask the owner to reactivate the account.")
        self._require_employee_password(employee, password)
        return employee

    def _require_request(self, payload: dict, request_id: str) -> dict:
        for request in payload["requests"]:
            if request["id"] == request_id:
                return request
        raise ValidationError("Leave request not found.")

    def _find_employee_month_request(self, payload: dict, employee_id: str, requested_day: date) -> dict | None:
        for request in payload["requests"]:
            existing_day = date.fromisoformat(request["date"])
            if request["employeeId"] == employee_id and existing_day.year == requested_day.year and existing_day.month == requested_day.month:
                return request
        return None

    def _validate_request_date(
        self,
        payload: dict,
        employee_id: str,
        request_date: str,
        ignore_request_id: str | None = None,
    ) -> date:
        try:
            requested_day = date.fromisoformat(request_date)
        except ValueError as error:
            raise ValidationError("Choose a valid leave date.") from error

        if requested_day.weekday() >= 5:
            raise ValidationError("Leave cannot be booked on Saturday or Sunday.")

        for request in payload["requests"]:
            if request["id"] == ignore_request_id:
                continue
            if request["employeeId"] == employee_id:
                continue
            if request.get("status") not in ACTIVE_REQUEST_STATUSES:
                continue
            if request["date"] != request_date:
                continue

            other_employee = self._employee_by_id(payload, request["employeeId"])
            other_name = other_employee["name"] if other_employee else "Another employee"
            status_label = "approved leave" if request.get("status") == "approved" else "pending request"
            raise ValidationError(f"{other_name} already has a {status_label} on {request_date}.")

        return requested_day


STORE = LeaveTrackerStore(STORE_PATH)


class LeaveTrackerHandler(BaseHTTPRequestHandler):
    server_version = "UTownLeaveTracker/2.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        if parsed.path == "/api/state":
            self._send_json(HTTPStatus.OK, STORE.public_snapshot())
            return

        if parsed.path == "/api/admin/state":
            self._require_admin()
            self._send_json(HTTPStatus.OK, STORE.admin_snapshot())
            return

        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        try:
            payload = self._read_json_body()

            if parsed.path == "/api/admin/verify":
                login_id = str(payload.get("loginId", ""))
                password = str(payload.get("password", ""))
                if not STORE.verify_admin(login_id, password):
                    raise ValidationError("The owner login ID or password is incorrect.")
                self._send_json(HTTPStatus.OK, {"ok": True, "ownerLoginId": STORE.owner_login_id()})
                return

            if parsed.path == "/api/admin/owner":
                self._require_admin()
                result = STORE.update_owner_credentials(
                    login_id=str(payload.get("loginId", "")),
                    password=str(payload.get("password", "")),
                )
                self._send_json(HTTPStatus.OK, {"ok": True, "owner": result})
                return

            if parsed.path == "/api/admin/employees":
                self._require_admin()
                employee = STORE.add_employee(
                    name=str(payload.get("name", "")),
                    password=str(payload.get("password", "")),
                )
                self._send_json(HTTPStatus.CREATED, {"ok": True, "employee": employee})
                return

            if parsed.path == "/api/admin/employees/status":
                self._require_admin()
                result = STORE.set_employee_status(
                    employee_id=str(payload.get("employeeId", "")),
                    active=bool(payload.get("active", True)),
                )
                self._send_json(HTTPStatus.OK, {"ok": True, "employee": result})
                return

            if parsed.path == "/api/admin/employees/password/reset":
                self._require_admin()
                result = STORE.reset_employee_password(
                    employee_id=str(payload.get("employeeId", "")),
                    password=str(payload.get("password", "")),
                )
                self._send_json(HTTPStatus.OK, {"ok": True, "employee": result})
                return

            if parsed.path == "/api/admin/requests/review":
                self._require_admin()
                result = STORE.review_request(
                    request_id=str(payload.get("requestId", "")),
                    action=str(payload.get("action", "")),
                )
                self._send_json(HTTPStatus.OK, {"ok": True, "request": result})
                return

            if parsed.path == "/api/employee/session":
                result = STORE.employee_session(
                    login_id=str(payload.get("loginId", "")),
                    password=str(payload.get("password", "")),
                )
                self._send_json(HTTPStatus.OK, {"ok": True, "session": result})
                return

            if parsed.path == "/api/employee/requests":
                result = STORE.submit_employee_request(
                    login_id=str(payload.get("loginId", "")),
                    password=str(payload.get("password", "")),
                    request_date=str(payload.get("date", "")),
                )
                self._send_json(HTTPStatus.OK, {"ok": True, "request": result})
                return

            if parsed.path == "/api/employee/requests/cancel":
                result = STORE.cancel_employee_request(
                    login_id=str(payload.get("loginId", "")),
                    password=str(payload.get("password", "")),
                    request_id=str(payload.get("requestId", "")),
                )
                self._send_json(HTTPStatus.OK, {"ok": True, "request": result})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found."})
        except ValidationError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body."})
        except Exception:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unexpected server error")

    def log_message(self, format_string: str, *args) -> None:
        return

    def _require_admin(self) -> None:
        login_id = self.headers.get("X-Admin-Login", "").strip()
        password = self.headers.get("X-Admin-Password", "")
        if not STORE.verify_admin(login_id, password):
            raise ValidationError("Owner access is required for that action.")

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, raw_path: str) -> None:
        target_path = raw_path or "/"
        if target_path == "/":
            file_path = PUBLIC_DIR / "index.html"
        else:
            relative_path = unquote(target_path.lstrip("/"))
            file_path = (PUBLIC_DIR / relative_path).resolve()

            if PUBLIC_DIR not in file_path.parents and file_path != PUBLIC_DIR:
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return

        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), LeaveTrackerHandler)
    current_owner_login_id = STORE.owner_login_id()
    print(f"UTown leave tracker running at http://{HOST}:{PORT}")
    print(f"Current owner login ID: {current_owner_login_id}")
    if STORE.owner_uses_default_credentials():
        print(f"Default owner password: {DEFAULT_OWNER_PASSWORD}")
    else:
        print("Owner password has already been customized.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
