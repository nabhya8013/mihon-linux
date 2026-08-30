"""
Shared persistent cookie jar for Python networking and the JVM bridge.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from .database import DATA_DIR, ensure_dirs


COOKIE_JAR_PATH = DATA_DIR / "cookies.json"
COOKIE_JAR_ENV = "MIHON_COOKIE_JAR"


def cookie_jar_path() -> Path:
    return COOKIE_JAR_PATH


def domain_from_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def load_cookie_records(path: Path = COOKIE_JAR_PATH) -> list[dict]:
    data = _load_payload(path)
    records = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return []
    return [record for record in records if _is_valid_record(record)]


def save_cookie_records(records: list[dict], path: Path = COOKIE_JAR_PATH) -> None:
    payload = _load_payload(path)
    payload["cookies"] = sorted(
        records,
        key=lambda item: (
            item.get("domain", ""),
            item.get("path", "/"),
            item.get("name", ""),
        ),
    )
    _save_payload(payload, path)


def load_user_agent_records(path: Path = COOKIE_JAR_PATH) -> list[dict]:
    data = _load_payload(path)
    records = data.get("user_agents") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return []
    return [record for record in records if _is_valid_user_agent_record(record)]


def save_user_agent_records(records: list[dict], path: Path = COOKIE_JAR_PATH) -> None:
    payload = _load_payload(path)
    payload["user_agents"] = sorted(records, key=lambda item: item.get("domain", ""))
    _save_payload(payload, path)


def load_cookies_into_session(session, path: Path = COOKIE_JAR_PATH) -> None:
    for record in load_cookie_records(path):
        _set_cookie(
            session.cookies,
            record["name"],
            record["value"],
            record["domain"],
            record.get("path") or "/",
            bool(record.get("secure", False)),
        )


def store_solution_cookies(
    url: str,
    cookies: Mapping[str, str],
    path: Path = COOKIE_JAR_PATH,
) -> None:
    domain = domain_from_url(url)
    if not domain or not cookies:
        return

    existing = load_cookie_records(path)
    by_key = {
        (record["domain"], record.get("path") or "/", record["name"]): record
        for record in existing
    }
    secure = urlparse(url).scheme == "https"
    now = time.time()
    for name, value in cookies.items():
        if not name:
            continue
        record = {
            "domain": domain,
            "path": "/",
            "name": str(name),
            "value": str(value),
            "secure": secure,
            "updated_at": now,
        }
        by_key[(domain, "/", str(name))] = record

    save_cookie_records(list(by_key.values()), path)


def store_solution_user_agent(
    url: str,
    user_agent: str,
    path: Path = COOKIE_JAR_PATH,
) -> None:
    domain = domain_from_url(url)
    if not domain or not user_agent:
        return
    records = load_user_agent_records(path)
    records = [record for record in records if record["domain"] != domain]
    records.append({
        "domain": domain,
        "user_agent": str(user_agent),
        "updated_at": time.time(),
    })
    save_user_agent_records(records, path)


def user_agent_for_url(url: str, path: Path = COOKIE_JAR_PATH) -> str:
    host = domain_from_url(url)
    if not host:
        return ""
    matches = [
        record
        for record in load_user_agent_records(path)
        if _domain_matches(host, record["domain"])
    ]
    if not matches:
        return ""
    matches.sort(key=lambda record: len(record["domain"]), reverse=True)
    return matches[0]["user_agent"]


def apply_cookies_to_session(session, url: str, cookies: Mapping[str, str]) -> None:
    domain = domain_from_url(url)
    if not domain:
        session.cookies.update(dict(cookies))
        return
    secure = urlparse(url).scheme == "https"
    for name, value in cookies.items():
        _set_cookie(session.cookies, str(name), str(value), domain, "/", secure)


def _set_cookie(cookie_jar, name: str, value: str, domain: str, path: str, secure: bool) -> None:
    setter = getattr(cookie_jar, "set", None)
    if setter:
        try:
            setter(name, value, domain=domain, path=path, secure=secure)
            return
        except TypeError:
            try:
                setter(name, value)
                return
            except TypeError:
                pass
    cookie_jar.update({name: value})


def _is_valid_record(record) -> bool:
    return (
        isinstance(record, dict)
        and isinstance(record.get("domain"), str)
        and isinstance(record.get("name"), str)
        and isinstance(record.get("value"), str)
    )


def _is_valid_user_agent_record(record) -> bool:
    return (
        isinstance(record, dict)
        and isinstance(record.get("domain"), str)
        and isinstance(record.get("user_agent"), str)
    )


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _load_payload(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "cookies": [], "user_agents": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "cookies": [], "user_agents": []}
    if not isinstance(data, dict):
        return {"version": 1, "cookies": [], "user_agents": []}
    data.setdefault("version", 1)
    data.setdefault("cookies", [])
    data.setdefault("user_agents", [])
    return data


def _save_payload(payload: dict, path: Path) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
