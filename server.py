"""Central service for the Printer Operations desktop application."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import shutil
import socket
import sqlite3
import ssl
import threading
import time
import zipfile
from datetime import date, datetime, time as daytime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

try:
    from pysnmp.hlapi.v1arch.asyncio import (
        CommunityData, ObjectIdentity, ObjectType, SnmpDispatcher,
        UdpTransportTarget, get_cmd, walk_cmd,
    )
except ImportError:
    CommunityData = None

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ContadoresImpressoras"
DB_PATH = APP_DIR / "operacao.sqlite3"
CERT_PATH = APP_DIR / "servidor.pem"
KEY_PATH = APP_DIR / "servidor-chave.pem"
INFO_PATH = APP_DIR / "conexao.txt"
HOST = "0.0.0.0"
PORT = 8765
POLL_SECONDS = 30
OFFLINE_FAILURES = 3
LOW_TONER_PERCENT = 5.0
TOKEN_TTL_HOURS = 12
PASSWORD_ITERATIONS = 310_000
LOG = logging.getLogger("printer-ops")

# Printer-MIB and Host-Resources-MIB fields used by the operational dashboard.
SCALARS = {
    "description": "1.3.6.1.2.1.1.1.0",
    "object_id": "1.3.6.1.2.1.1.2.0",
    "uptime": "1.3.6.1.2.1.1.3.0",
    "hostname": "1.3.6.1.2.1.1.5.0",
    "printer_name": "1.3.6.1.2.1.43.5.1.1.16.1",
    "serial": "1.3.6.1.2.1.43.5.1.1.17.1",
    "printer_state": "1.3.6.1.2.1.25.3.5.1.1.1",
    "printer_errors": "1.3.6.1.2.1.25.3.5.1.2.1",
}
COUNTER_UNIT_ROOT = "1.3.6.1.2.1.43.10.2.1.3"
COUNTER_LIFE_ROOT = "1.3.6.1.2.1.43.10.2.1.4"
COUNTER_POWER_ROOT = "1.3.6.1.2.1.43.10.2.1.5"
SUPPLY_ROOTS = {
    "description": "1.3.6.1.2.1.43.11.1.1.6",
    "unit": "1.3.6.1.2.1.43.11.1.1.7",
    "maximum": "1.3.6.1.2.1.43.11.1.1.8",
    "level": "1.3.6.1.2.1.43.11.1.1.9",
}
TRAY_ROOTS = {
    "capacity": "1.3.6.1.2.1.43.8.2.1.9",
    "status": "1.3.6.1.2.1.43.8.2.1.10",
    "media": "1.3.6.1.2.1.43.8.2.1.11",
    "name": "1.3.6.1.2.1.43.8.2.1.13",
}
COUNTER_UNITS = {
    3: "0,0001 polegada", 4: "micrômetros", 5: "caracteres", 6: "linhas",
    7: "impressões", 8: "folhas", 9: "linhas de pontos", 11: "horas",
    16: "pés", 17: "metros",
}
PRINTER_STATES = {1: "Outro", 2: "Desconhecido", 3: "Ociosa", 4: "Imprimindo", 5: "Aquecendo"}
TRAY_STATES = {1: "Outro", 2: "Desconhecido", 3: "Vazia", 4: "Carregada", 5: "Retirada", 6: "Saída cheia", 7: "Faltando"}
PRINTER_ERROR_BITS = {
    0: "Papel baixo", 1: "Sem papel", 2: "Toner baixo", 3: "Sem toner",
    4: "Tampa aberta", 5: "Papel atolado", 6: "Impressora offline", 7: "Manutenção necessária",
    8: "Bandeja de entrada ausente", 9: "Bandeja de saída ausente", 10: "Suprimento ausente",
    11: "Saída quase cheia", 12: "Saída cheia", 13: "Bandeja de entrada vazia", 14: "Manutenção vencida",
}


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


def db_connect() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA busy_timeout = 30000")
    return db


def init_db() -> None:
    with db_connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                salt BLOB NOT NULL, password_hash BLOB NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS printers (
                id INTEGER PRIMARY KEY, alias TEXT NOT NULL, ip TEXT NOT NULL UNIQUE,
                community TEXT NOT NULL DEFAULT '', version TEXT NOT NULL DEFAULT '2c',
                photo BLOB, photo_mime TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS current_status (
                printer_id INTEGER PRIMARY KEY REFERENCES printers(id) ON DELETE CASCADE,
                online INTEGER NOT NULL DEFAULT -1, status TEXT NOT NULL DEFAULT 'Ainda não consultada',
                last_poll TEXT, last_success TEXT, failures INTEGER NOT NULL DEFAULT 0,
                counter INTEGER, unit TEXT, data_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY, printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE CASCADE,
                recorded_at TEXT NOT NULL, counter INTEGER, unit TEXT, status TEXT NOT NULL,
                data_json TEXT NOT NULL, kind TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_printer_time ON history(printer_id, recorded_at);
            CREATE TABLE IF NOT EXISTS daily_totals (
                printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE CASCADE,
                local_date TEXT NOT NULL, unit TEXT NOT NULL, impressions INTEGER NOT NULL DEFAULT 0,
                estimated INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
                PRIMARY KEY (printer_id, local_date, unit)
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY, printer_id INTEGER REFERENCES printers(id) ON DELETE CASCADE,
                alert_type TEXT NOT NULL, signature TEXT NOT NULL DEFAULT '', message TEXT NOT NULL,
                created_at TEXT NOT NULL, resolved_at TEXT, active INTEGER NOT NULL DEFAULT 1,
                acknowledged_by TEXT, acknowledged_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active, created_at);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS backup_log (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, path TEXT NOT NULL,
                success INTEGER NOT NULL, message TEXT NOT NULL
            );
        """)
        defaults = {
            "backup_path": "", "backup_retention_days": "30", "last_backup_date": "",
            "last_backup_at": "", "last_backup_attempt_at": "", "last_backup_message": "Backup ainda não executado",
        }
        for key, value in defaults.items():
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))
        seeded = db.execute("SELECT value FROM settings WHERE key='initial_inventory_initialized'").fetchone()
        if not seeded:
            # Each deployment starts without device addresses or shared credentials.
            db.execute("INSERT INTO settings(key,value) VALUES('initial_inventory_initialized','1')")


def set_setting(key: str, value: str) -> None:
    with db_connect() as db:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_settings(db: sqlite3.Connection) -> dict:
    return {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM settings")}


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return salt, digest


def add_user(username: str, password: str) -> int:
    username = username.strip()
    if not username or len(username) > 64:
        raise ValueError("O nome de usuário deve ter de 1 a 64 caracteres.")
    if len(password) < 12:
        raise ValueError("Use uma senha com pelo menos 12 caracteres.")
    salt, digest = hash_password(password)
    with db_connect() as db:
        cur = db.execute("INSERT INTO users(username,salt,password_hash,created_at) VALUES(?,?,?,?)", (username, salt, digest, iso_now()))
        return int(cur.lastrowid)


def verify_user(username: str, password: str) -> sqlite3.Row | None:
    with db_connect() as db:
        row = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username.strip(),)).fetchone()
    if not row:
        return None
    _, digest = hash_password(password, row["salt"])
    return row if hmac.compare_digest(digest, row["password_hash"]) else None


def new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(40)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = (now_local() + timedelta(hours=TOKEN_TTL_HOURS)).isoformat(timespec="seconds")
    with db_connect() as db:
        db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (token_hash, user_id, expires))
    return token


def authenticated_user(handler: BaseHTTPRequestHandler) -> sqlite3.Row | None:
    raw = handler.headers.get("Authorization", "")
    if not raw.startswith("Bearer "):
        return None
    token_hash = hashlib.sha256(raw[7:].strip().encode()).hexdigest()
    with db_connect() as db:
        return db.execute("""
            SELECT u.id,u.username FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1
        """, (token_hash, iso_now())).fetchone()


def revoke_session(handler: BaseHTTPRequestHandler) -> None:
    raw = handler.headers.get("Authorization", "")
    if raw.startswith("Bearer "):
        token_hash = hashlib.sha256(raw[7:].strip().encode()).hexdigest()
        with db_connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))


def pval(value):
    if value is None:
        return None
    name = type(value).__name__.lower()
    if "nosuch" in name or "endofmib" in name:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        result = str(value).strip()
        return result if result and not result.startswith("No Such") else None


async def get_scalars(dispatcher, auth, target) -> dict:
    objects = [ObjectType(ObjectIdentity(oid)) for oid in SCALARS.values()]
    err, status, _, binds = await get_cmd(dispatcher, auth, target, *objects, lookupMib=False)
    if err:
        raise RuntimeError(str(err))
    if status:
        raise RuntimeError(f"Resposta SNMP com erro: {status}")
    result = {}
    for (name, _), bind in zip(SCALARS.items(), binds):
        value = bind[1]
        if name == "printer_errors" and "nosuch" not in type(value).__name__.lower():
            try:
                result[name] = bytes(value).hex()
                continue
            except (TypeError, ValueError):
                pass
        result[name] = pval(value)
    return result


def decode_printer_errors(raw_hex) -> list[str]:
    if not isinstance(raw_hex, str):
        return []
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError:
        return []
    found = []
    for bit, label in PRINTER_ERROR_BITS.items():
        byte_index, bit_index = divmod(bit, 8)
        if byte_index < len(raw) and raw[byte_index] & (1 << (7 - bit_index)):
            found.append(label)
    return found


async def walk_column(dispatcher, auth, target, root: str) -> dict[str, object]:
    rows = {}
    async for err, status, _, binds in walk_cmd(
        dispatcher, auth, target, ObjectType(ObjectIdentity(root)),
        lexicographicMode=False, lookupMib=False,
    ):
        if err:
            raise RuntimeError(str(err))
        if status:
            # Some devices implement only part of Printer-MIB. A missing optional
            # table is not evidence that the printer itself is offline.
            if rows:
                break
            return {}
        for oid, value in binds:
            text_oid = str(oid)
            prefix = root + "."
            if not text_oid.startswith(prefix):
                continue
            suffix = text_oid[len(prefix):]
            rows[suffix] = pval(value)
    return rows


async def read_printer(printer: dict) -> dict:
    if CommunityData is None:
        raise RuntimeError("Dependência pysnmp ausente; execute instalar_servidor.bat.")
    dispatcher = SnmpDispatcher()
    auth = CommunityData(printer["community"], mpModel=0 if printer["version"] == "1" else 1)
    target = await UdpTransportTarget.create((printer["ip"], 161), timeout=2, retries=0)
    try:
        scalars = await get_scalars(dispatcher, auth, target)
        counters, units, power = await asyncio.gather(
            walk_column(dispatcher, auth, target, COUNTER_LIFE_ROOT),
            walk_column(dispatcher, auth, target, COUNTER_UNIT_ROOT),
            walk_column(dispatcher, auth, target, COUNTER_POWER_ROOT),
        )
        counter_rows = [(int(value), suffix) for suffix, value in counters.items() if isinstance(value, int) and value >= 0]
        counter, counter_index = max(counter_rows, default=(None, None))
        unit_code = units.get(counter_index) if counter_index else None
        unit_name = COUNTER_UNITS.get(unit_code, f"unidade SNMP {unit_code}" if unit_code is not None else "unidade desconhecida")
        power_count = power.get(counter_index) if counter_index else None

        supply_columns = await asyncio.gather(*(walk_column(dispatcher, auth, target, root) for root in SUPPLY_ROOTS.values()))
        supply_maps = {name: values for (name, _), values in zip(SUPPLY_ROOTS.items(), supply_columns)}
        supply_ids = set().union(*(set(values) for values in supply_maps.values()))
        supplies = []
        for index in sorted(supply_ids):
            description = supply_maps["description"].get(index) or "Suprimento"
            level = supply_maps["level"].get(index)
            maximum = supply_maps["maximum"].get(index)
            supply_unit = supply_maps["unit"].get(index)
            percent = None
            if isinstance(level, int) and level >= 0:
                if supply_unit == 19:
                    percent = max(0, min(100, round(level)))
                elif isinstance(maximum, int) and maximum > 0:
                    percent = max(0, min(100, round(100 * level / maximum)))
            supplies.append({"name": str(description), "level": level, "maximum": maximum, "percent": percent, "unit": supply_unit})

        tray_columns = await asyncio.gather(*(walk_column(dispatcher, auth, target, root) for root in TRAY_ROOTS.values()))
        tray_maps = {name: values for (name, _), values in zip(TRAY_ROOTS.items(), tray_columns)}
        trays = []
        for index in sorted(set().union(*(set(values) for values in tray_maps.values()))):
            tray_state = tray_maps["status"].get(index)
            name = tray_maps["name"].get(index) or f"Bandeja {index}"
            trays.append({"name": str(name), "status": TRAY_STATES.get(tray_state, str(tray_state) if tray_state is not None else "Desconhecido"), "capacity": tray_maps["capacity"].get(index), "media": tray_maps["media"].get(index)})

        state_code = scalars.get("printer_state")
        reported_errors = decode_printer_errors(scalars.get("printer_errors"))
        base_status = PRINTER_STATES.get(state_code, f"Estado SNMP {state_code}" if state_code is not None else "Desconhecido")
        status_label = f"{base_status} · {reported_errors[0]}" if reported_errors else base_status
        uptime_ticks = scalars.get("uptime")
        uptime_seconds = round(uptime_ticks / 100) if isinstance(uptime_ticks, int) else None
        return {
            "model": scalars.get("description") or "Modelo não informado",
            "object_id": scalars.get("object_id"),
            "hostname": scalars.get("hostname"),
            "printer_name": scalars.get("printer_name"),
            "serial": scalars.get("serial"),
            "status": status_label,
            "status_code": state_code,
            "errors_raw": scalars.get("printer_errors"),
            "reported_errors": reported_errors,
            "uptime_seconds": uptime_seconds,
            "counter": counter,
            "counter_unit": unit_name,
            "counter_unit_code": unit_code,
            "counter_since_power_on": power_count,
            "supplies": supplies,
            "trays": trays,
        }
    finally:
        dispatcher.close()


def data_signature(data: dict) -> str:
    keep = {key: data.get(key) for key in ("model", "serial", "status", "counter", "counter_unit", "supplies", "trays")}
    return json.dumps(keep, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def add_daily_delta(db: sqlite3.Connection, printer_id: int, previous: sqlite3.Row | None, data: dict, observed_at: datetime) -> tuple[int, bool]:
    current = data.get("counter")
    unit = data.get("counter_unit", "unidade desconhecida")
    if not isinstance(current, int):
        return 0, False
    if not previous or previous["counter"] is None:
        db.execute("INSERT INTO daily_totals(printer_id,local_date,unit,impressions,estimated,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(printer_id,local_date,unit) DO NOTHING", (printer_id, observed_at.date().isoformat(), unit, 0, 0, observed_at.isoformat(timespec="seconds")))
        return 0, False
    if previous["unit"] and previous["unit"] != unit:
        db.execute("INSERT INTO daily_totals(printer_id,local_date,unit,impressions,estimated,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(printer_id,local_date,unit) DO NOTHING", (printer_id, observed_at.date().isoformat(), unit, 0, 1, observed_at.isoformat(timespec="seconds")))
        return 0, True
    old = int(previous["counter"])
    if current >= old:
        delta = current - old
    elif old > 4_000_000_000 and current < 1_000_000:
        delta = (2 ** 32 - old) + current
    else:
        db.execute("INSERT INTO daily_totals(printer_id,local_date,unit,impressions,estimated,updated_at) VALUES(?,?,?,?,1,?) ON CONFLICT(printer_id,local_date,unit) DO UPDATE SET estimated=1,updated_at=excluded.updated_at", (printer_id, observed_at.date().isoformat(), unit, 0, observed_at.isoformat(timespec="seconds")))
        return 0, True  # Counter reset: establish a new baseline without a negative daily total.
    if not delta:
        return 0, False
    previous_time = datetime.fromisoformat(previous["last_success"]) if previous["last_success"] else observed_at
    if previous_time.tzinfo is None:
        previous_time = previous_time.astimezone()
    gap = max(0.0, (observed_at - previous_time).total_seconds())
    estimated = False
    portions: list[tuple[date, int]]
    if previous_time.date() == observed_at.date():
        portions = [(observed_at.date(), delta)]
    elif gap > 0 and gap <= 120 and (observed_at.date() - previous_time.date()).days == 1:
        midnight = datetime.combine(observed_at.date(), daytime.min, tzinfo=observed_at.tzinfo)
        before_seconds = max(0.0, (midnight - previous_time).total_seconds())
        before_delta = max(0, min(delta, round(delta * before_seconds / gap)))
        portions = [(previous_time.date(), before_delta), (observed_at.date(), delta - before_delta)]
        estimated = True
    else:
        portions = [(observed_at.date(), delta)]
        estimated = gap > 120
    for day, amount in portions:
        if amount:
            db.execute("""
                INSERT INTO daily_totals(printer_id,local_date,unit,impressions,estimated,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(printer_id,local_date,unit) DO UPDATE SET
                impressions=impressions+excluded.impressions,
                estimated=MAX(estimated,excluded.estimated), updated_at=excluded.updated_at
            """, (printer_id, day.isoformat(), unit, amount, int(estimated), observed_at.isoformat(timespec="seconds")))
    return delta, estimated


def open_alert(db: sqlite3.Connection, printer_id: int | None, alert_type: str, signature: str, message: str) -> None:
    existing = db.execute("SELECT id FROM alerts WHERE printer_id IS ? AND alert_type=? AND signature=? AND active=1", (printer_id, alert_type, signature)).fetchone()
    if not existing:
        db.execute("INSERT INTO alerts(printer_id,alert_type,signature,message,created_at,active) VALUES(?,?,?,?,?,1)", (printer_id, alert_type, signature, message, iso_now()))


def resolve_alerts(db: sqlite3.Connection, printer_id: int | None, alert_type: str, signature: str | None = None) -> None:
    if signature is None:
        db.execute("UPDATE alerts SET active=0,resolved_at=? WHERE printer_id IS ? AND alert_type=? AND active=1", (iso_now(), printer_id, alert_type))
    else:
        db.execute("UPDATE alerts SET active=0,resolved_at=? WHERE printer_id IS ? AND alert_type=? AND signature=? AND active=1", (iso_now(), printer_id, alert_type, signature))


def store_success(printer: dict, data: dict) -> None:
    observed = now_local()
    recorded = observed.isoformat(timespec="seconds")
    payload = json.dumps(data, ensure_ascii=False)
    with db_connect() as db:
        previous = db.execute("SELECT * FROM current_status WHERE printer_id=?", (printer["id"],)).fetchone()
        previous_data = json.loads(previous["data_json"] or "{}") if previous else {}
        previous_sig = data_signature(previous_data) if previous and previous["last_success"] else None
        current_sig = data_signature(data)
        _, reset = add_daily_delta(db, printer["id"], previous, data, observed)
        db.execute("""
            INSERT INTO current_status(printer_id,online,status,last_poll,last_success,failures,counter,unit,data_json,error)
            VALUES(?,1,?,?,?,?,?,?,?, '')
            ON CONFLICT(printer_id) DO UPDATE SET online=1,status=excluded.status,last_poll=excluded.last_poll,
            last_success=excluded.last_success,failures=0,counter=excluded.counter,unit=excluded.unit,
            data_json=excluded.data_json,error=''
        """, (printer["id"], data["status"], recorded, recorded, 0, data.get("counter"), data.get("counter_unit"), payload))
        last_history = db.execute("SELECT recorded_at,kind FROM history WHERE printer_id=? ORDER BY id DESC LIMIT 1", (printer["id"],)).fetchone()
        hour_key = observed.strftime("%Y-%m-%d %H")
        last_hour_key = datetime.fromisoformat(last_history["recorded_at"]).strftime("%Y-%m-%d %H") if last_history else None
        if not last_history:
            kind = "baseline"
        elif reset:
            kind = "contador_reiniciado"
        elif previous_sig != current_sig:
            kind = "mudanca"
        elif last_hour_key != hour_key:
            kind = "resumo_horario"
        else:
            kind = None
        if kind:
            db.execute("INSERT INTO history(printer_id,recorded_at,counter,unit,status,data_json,kind) VALUES(?,?,?,?,?,?,?)", (printer["id"], recorded, data.get("counter"), data.get("counter_unit"), data["status"], payload, kind))

        resolve_alerts(db, printer["id"], "offline")
        reported = data.get("reported_errors", [])
        active_device_alerts = {row["signature"] for row in db.execute("SELECT signature FROM alerts WHERE printer_id=? AND alert_type='device_error' AND active=1", (printer["id"],)).fetchall()}
        for issue in reported:
            signature = "device:" + issue.casefold()
            open_alert(db, printer["id"], "device_error", signature, f"{printer['alias']}: {issue}.")
        for signature in active_device_alerts:
            if signature not in {"device:" + issue.casefold() for issue in reported}:
                resolve_alerts(db, printer["id"], "device_error", signature)
        for supply in data.get("supplies", []):
            name = supply.get("name") or "Suprimento"
            percent = supply.get("percent")
            sig = "toner:" + name.casefold()
            if "toner" in name.casefold() and isinstance(percent, (int, float)):
                if percent <= LOW_TONER_PERCENT:
                    open_alert(db, printer["id"], "toner", sig, f"{printer['alias']}: {name} em {percent:.0f}% (limite {LOW_TONER_PERCENT:.0f}%).")
                else:
                    resolve_alerts(db, printer["id"], "toner", sig)
        # A missing supply reading is not treated as toner recovery; only a reported healthy level resolves it.


def store_failure(printer: dict, error: str) -> None:
    recorded = iso_now()
    with db_connect() as db:
        previous = db.execute("SELECT * FROM current_status WHERE printer_id=?", (printer["id"],)).fetchone()
        failures = (previous["failures"] if previous else 0) + 1
        online = 0 if failures >= OFFLINE_FAILURES else -1
        state = "Offline" if online == 0 else f"Sem resposta ({failures}/{OFFLINE_FAILURES})"
        db.execute("""
            INSERT INTO current_status(printer_id,online,status,last_poll,last_success,failures,counter,unit,data_json,error)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(printer_id) DO UPDATE SET online=excluded.online,status=excluded.status,
            last_poll=excluded.last_poll,failures=excluded.failures,error=excluded.error
        """, (printer["id"], online, state, recorded, previous["last_success"] if previous else None, failures,
              previous["counter"] if previous else None, previous["unit"] if previous else None,
              previous["data_json"] if previous else "{}", error[:500]))
        if failures == OFFLINE_FAILURES:
            open_alert(db, printer["id"], "offline", "no_response", f"{printer['alias']} ({printer['ip']}) sem resposta SNMP após {OFFLINE_FAILURES} consultas.")


async def poll_all() -> None:
    with db_connect() as db:
        printers = [dict(row) for row in db.execute("SELECT * FROM printers ORDER BY id").fetchall()]
    if not printers:
        return
    results = await asyncio.gather(*(read_printer(p) for p in printers), return_exceptions=True)
    for printer, result in zip(printers, results):
        if isinstance(result, BaseException):
            store_failure(printer, str(result))
        else:
            store_success(printer, result)


def create_backup(path: str) -> str:
    dest = Path(path).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    stamp = now_local().strftime("%Y%m%d_%H%M%S")
    temp_db = APP_DIR / f"backup_{stamp}.sqlite3"
    archive = dest / f"contadores_{stamp}.zip"
    source = db_connect()
    target = sqlite3.connect(temp_db)
    try:
        source.backup(target)
        target.close()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(temp_db, arcname="operacao.sqlite3")
    finally:
        try:
            source.close()
        except Exception:
            pass
        try:
            target.close()
        except Exception:
            pass
        temp_db.unlink(missing_ok=True)
    return str(archive)


def run_backup_if_due() -> None:
    with db_connect() as db:
        settings = get_settings(db)
        backup_path = settings.get("backup_path", "").strip()
        last_date = settings.get("last_backup_date", "")
    now = now_local()
    if now.time() < daytime(2, 0) or last_date == now.date().isoformat():
        return
    last_attempt = settings.get("last_backup_attempt_at", "")
    if last_attempt:
        try:
            if (now - datetime.fromisoformat(last_attempt)).total_seconds() < 3600:
                return
        except ValueError:
            pass
    if not backup_path:
        with db_connect() as db:
            open_alert(db, None, "backup", "backup_unconfigured", "Configure uma pasta compartilhada para ativar o backup diário.")
        return
    set_setting("last_backup_attempt_at", iso_now())
    try:
        archive = create_backup(backup_path)
        retention = 30
        try:
            retention = max(1, min(3650, int(settings.get("backup_retention_days", "30"))))
        except ValueError:
            pass
        cutoff = now.date() - timedelta(days=retention)
        for item in Path(backup_path).glob("contadores_*.zip"):
            try:
                stamp = item.stem.removeprefix("contadores_")[:8]
                if datetime.strptime(stamp, "%Y%m%d").date() < cutoff:
                    item.unlink()
            except (ValueError, OSError):
                continue
        set_setting("last_backup_date", now.date().isoformat())
        set_setting("last_backup_at", iso_now())
        set_setting("last_backup_message", f"Concluído: {archive}")
        with db_connect() as db:
            db.execute("INSERT INTO backup_log(created_at,path,success,message) VALUES(?,?,1,?)", (iso_now(), archive, "Backup diário concluído"))
            resolve_alerts(db, None, "backup")
    except Exception as exc:
        set_setting("last_backup_message", f"Falha: {exc}")
        with db_connect() as db:
            db.execute("INSERT INTO backup_log(created_at,path,success,message) VALUES(?,?,0,?)", (iso_now(), backup_path, str(exc)[:500]))
            open_alert(db, None, "backup", "backup_failed", f"Falha no backup diário: {exc}")


def poller_loop(stop: threading.Event) -> None:
    next_poll = 0.0
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_poll:
            try:
                asyncio.run(poll_all())
            except Exception:
                LOG.exception("Falha no ciclo SNMP")
            try:
                run_backup_if_due()
            except Exception:
                LOG.exception("Falha ao verificar o backup")
            next_poll = time.monotonic() + POLL_SECONDS
        stop.wait(min(1.0, max(0.1, next_poll - time.monotonic())))


def build_certificate() -> tuple[Path, Path, str]:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not CERT_PATH.exists() or not KEY_PATH.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        hostname = socket.gethostname()
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname), x509.DNSName("localhost")]), critical=False)
                .sign(key, hashes.SHA256()))
        KEY_PATH.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(CERT_PATH.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    fingerprint = hashlib.sha256(der).hexdigest()
    return CERT_PATH, KEY_PATH, fingerprint


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def row_printer(db: sqlite3.Connection, printer_id: int) -> dict | None:
    row = db.execute("SELECT p.*,c.online,c.status,c.last_poll,c.last_success,c.failures,c.counter,c.unit,c.data_json,c.error FROM printers p LEFT JOIN current_status c ON c.printer_id=p.id WHERE p.id=?", (printer_id,)).fetchone()
    if not row:
        return None
    return printer_view(db, row)


def printer_view(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    try:
        data = json.loads(row["data_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        data = {}
    today = now_local().date().isoformat()
    daily = db.execute("SELECT unit,SUM(impressions) AS total,MAX(estimated) AS estimated FROM daily_totals WHERE printer_id=? AND local_date=? GROUP BY unit", (row["id"], today)).fetchall()
    totals = [{"unit": r["unit"], "impressions": r["total"], "estimated": bool(r["estimated"])} for r in daily]
    return {
        "id": row["id"], "alias": row["alias"], "ip": row["ip"], "version": row["version"],
        "community": row["community"],
        "online": row["online"] if row["online"] is not None else -1,
        "status": row["status"] or "Ainda não consultada", "last_poll": row["last_poll"],
        "last_success": row["last_success"], "failures": row["failures"] or 0,
        "counter": row["counter"], "unit": row["unit"], "error": row["error"] or "",
        "data": data, "today": totals,
        "has_photo": bool(row["has_photo"] if "has_photo" in row.keys() else row["photo"]), "photo_mime": row["photo_mime"],
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "PrinterOps/1.0"

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.client_address[0], fmt % args)

    def send_json(self, status: int, value) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body_json(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size > 8_000_000:
            raise ValueError("Arquivo ou solicitação excede o limite de 8 MB.")
        if size <= 0:
            return {}
        parsed = json.loads(self.rfile.read(size).decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Corpo JSON inválido.")
        return parsed

    def require_user(self):
        user = authenticated_user(self)
        if not user:
            self.send_json(401, {"error": "Sessão inválida ou expirada. Entre novamente."})
        return user

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/api/status":
                with db_connect() as db:
                    count = db.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
                self.send_json(200, {"needs_setup": count == 0, "poll_seconds": POLL_SECONDS, "product": "Contadores de Impressoras"})
                return
            if path == "/api/login":
                self.send_json(405, {"error": "Use POST para entrar."})
                return
            user = self.require_user()
            if not user:
                return
            if path == "/api/dashboard":
                with db_connect() as db:
                    rows = db.execute("SELECT p.id,p.alias,p.ip,p.community,p.version,p.photo_mime,CASE WHEN p.photo IS NULL THEN 0 ELSE 1 END AS has_photo,c.online,c.status,c.last_poll,c.last_success,c.failures,c.counter,c.unit,c.data_json,c.error FROM printers p LEFT JOIN current_status c ON c.printer_id=p.id ORDER BY p.alias COLLATE NOCASE").fetchall()
                    printers = [printer_view(db, row) for row in rows]
                    active = db.execute("SELECT COUNT(*) FROM alerts WHERE active=1").fetchone()[0]
                    today = now_local().date().isoformat()
                    total = db.execute("SELECT unit,SUM(impressions) AS n,MAX(estimated) AS estimated FROM daily_totals WHERE local_date=? GROUP BY unit", (today,)).fetchall()
                self.send_json(200, {"printers": printers, "active_alerts": active,
                                     "online": sum(p["online"] == 1 for p in printers),
                                     "offline": sum(p["online"] == 0 for p in printers),
                                     "printing": sum(p["online"] == 1 and p["data"].get("status", "").startswith("Imprimindo") for p in printers),
                                     "daily_totals": [{"unit": r["unit"], "impressions": r["n"] or 0, "estimated": bool(r["estimated"])} for r in total],
                                     "server_time": iso_now(), "user": user["username"]})
                return
            if path == "/api/printers":
                with db_connect() as db:
                    rows = db.execute("SELECT p.id,p.alias,p.ip,p.community,p.version,p.photo_mime,CASE WHEN p.photo IS NULL THEN 0 ELSE 1 END AS has_photo,c.online,c.status,c.last_poll,c.last_success,c.failures,c.counter,c.unit,c.data_json,c.error FROM printers p LEFT JOIN current_status c ON c.printer_id=p.id ORDER BY p.alias COLLATE NOCASE").fetchall()
                    self.send_json(200, [printer_view(db, row) for row in rows])
                return
            if path.startswith("/api/printers/") and path.endswith("/photo"):
                printer_id = int(path.split("/")[3])
                with db_connect() as db:
                    row = db.execute("SELECT photo,photo_mime FROM printers WHERE id=?", (printer_id,)).fetchone()
                if not row or not row["photo"]:
                    self.send_json(404, {"error": "Imagem não cadastrada."})
                else:
                    self.send_json(200, {"mime": row["photo_mime"], "base64": base64.b64encode(row["photo"]).decode("ascii")})
                return
            if path == "/api/alerts":
                active_only = query.get("active", ["0"])[0] == "1"
                with db_connect() as db:
                    where = "WHERE a.active=1" if active_only else ""
                    rows = db.execute(f"""SELECT a.*,p.alias,p.ip FROM alerts a LEFT JOIN printers p ON p.id=a.printer_id {where} ORDER BY a.active DESC,a.created_at DESC LIMIT 300""").fetchall()
                self.send_json(200, [dict(row) for row in rows])
                return
            if path == "/api/reports/daily":
                day = query.get("date", [now_local().date().isoformat()])[0]
                date.fromisoformat(day)
                with db_connect() as db:
                    rows = db.execute("""
                        SELECT p.id,p.alias,p.ip,d.unit,d.impressions,d.estimated
                        FROM printers p LEFT JOIN daily_totals d ON d.printer_id=p.id AND d.local_date=?
                        ORDER BY p.alias COLLATE NOCASE
                    """, (day,)).fetchall()
                result = [dict(row) for row in rows]
                totals = {}
                for row in result:
                    if row["unit"]:
                        totals[row["unit"]] = totals.get(row["unit"], 0) + (row["impressions"] or 0)
                self.send_json(200, {"date": day, "printers": result, "totals": totals})
                return
            if path == "/api/reports/range":
                start = date.fromisoformat(query.get("start", [""])[0])
                end = date.fromisoformat(query.get("end", [""])[0])
                if end < start or (end - start).days > 3660:
                    raise ValueError("Período inválido; limite de 10 anos por consulta.")
                with db_connect() as db:
                    rows = db.execute("""
                        SELECT p.alias,p.ip,d.local_date,d.unit,d.impressions,d.estimated
                        FROM daily_totals d JOIN printers p ON p.id=d.printer_id
                        WHERE d.local_date BETWEEN ? AND ? ORDER BY d.local_date,p.alias COLLATE NOCASE
                    """, (start.isoformat(), end.isoformat())).fetchall()
                detail_rows = [dict(row) for row in rows]
                daily = {}
                for row in detail_rows:
                    key = (row["local_date"], row["unit"])
                    summary = daily.setdefault(key, {"local_date": row["local_date"], "unit": row["unit"], "impressions": 0, "estimated": False})
                    summary["impressions"] += row["impressions"] or 0
                    summary["estimated"] = summary["estimated"] or bool(row["estimated"])
                self.send_json(200, {"start": start.isoformat(), "end": end.isoformat(), "rows": detail_rows,
                                     "daily_totals": sorted(daily.values(), key=lambda x: (x["local_date"], x["unit"]))})
                return
            if path == "/api/users":
                with db_connect() as db:
                    rows = db.execute("SELECT id,username,active,created_at FROM users ORDER BY username COLLATE NOCASE").fetchall()
                self.send_json(200, [dict(row) for row in rows])
                return
            if path == "/api/settings":
                with db_connect() as db:
                    settings = get_settings(db)
                self.send_json(200, {"backup_path": settings.get("backup_path", ""),
                                     "backup_retention_days": int(settings.get("backup_retention_days", "30")),
                                     "last_backup_at": settings.get("last_backup_at", ""),
                                     "last_backup_message": settings.get("last_backup_message", ""),
                                     "backup_schedule": "Diariamente após 02:00, horário local"})
                return
            if path == "/api/history":
                start = query.get("start", [""])[0]
                end = query.get("end", [""])[0]
                date.fromisoformat(start); date.fromisoformat(end)
                if end < start or (date.fromisoformat(end) - date.fromisoformat(start)).days > 3660:
                    raise ValueError("Período inválido; limite de 10 anos por consulta.")
                printer_id = query.get("printer_id", [""])[0]
                sql = "SELECT h.*,p.alias,p.ip FROM history h JOIN printers p ON p.id=h.printer_id WHERE h.recorded_at>=? AND h.recorded_at<?"
                params: list[object] = [start + "T00:00:00", (date.fromisoformat(end) + timedelta(days=1)).isoformat() + "T00:00:00"]
                if printer_id:
                    sql += " AND h.printer_id=?"; params.append(int(printer_id))
                sql += " ORDER BY h.recorded_at DESC LIMIT 50000"
                with db_connect() as db:
                    rows = db.execute(sql, params).fetchall()
                self.send_json(200, [dict(row) for row in rows])
                return
            self.send_json(404, {"error": "Rota não encontrada."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            LOG.exception("GET %s falhou", path)
            self.send_json(500, {"error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self.body_json()
            if path == "/api/setup":
                with db_connect() as db:
                    existing = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                if existing:
                    self.send_json(409, {"error": "A configuração inicial já foi concluída."}); return
                username = str(payload.get("username", "")); password = str(payload.get("password", ""))
                user_id = add_user(username, password)
                self.send_json(201, {"token": new_session(user_id), "username": username}); return
            if path == "/api/login":
                row = verify_user(str(payload.get("username", "")), str(payload.get("password", "")))
                if not row:
                    self.send_json(401, {"error": "Usuário ou senha inválidos."}); return
                self.send_json(200, {"token": new_session(row["id"]), "username": row["username"]}); return
            if path == "/api/logout":
                revoke_session(self); self.send_json(200, {"ok": True}); return
            user = self.require_user()
            if not user:
                return
            if path == "/api/printers":
                alias = str(payload.get("alias", "")).strip()
                ip = str(payload.get("ip", "")).strip()
                community = str(payload.get("community", "")).strip()
                version = str(payload.get("version", "2c"))
                ipaddress.ip_address(ip)
                if not alias or not community or version not in ("1", "2c"):
                    raise ValueError("Informe nome, comunidade SNMP e versão 1 ou 2c.")
                with db_connect() as db:
                    cur = db.execute("INSERT INTO printers(alias,ip,community,version,created_at) VALUES(?,?,?,?,?)", (alias, ip, community, version, iso_now()))
                    printer_id = int(cur.lastrowid)
                self.send_json(201, {"id": printer_id, "message": "Equipamento cadastrado; a primeira consulta ocorrerá em instantes."}); return
            if path == "/api/users":
                user_id = add_user(str(payload.get("username", "")), str(payload.get("password", "")))
                self.send_json(201, {"id": user_id, "message": "Conta administrativa criada."}); return
            if path == "/api/backup/test":
                with db_connect() as db:
                    settings = get_settings(db)
                target = str(payload.get("path") or settings.get("backup_path", "")).strip()
                if not target:
                    raise ValueError("Informe a pasta compartilhada para backup.")
                test_path = Path(target).expanduser()
                test_path.mkdir(parents=True, exist_ok=True)
                probe = test_path / f".teste_contadores_{secrets.token_hex(4)}"
                probe.write_text("teste de acesso", encoding="utf-8")
                probe.unlink()
                self.send_json(200, {"ok": True, "message": "A pasta permite gravação a partir do computador central."}); return
            self.send_json(404, {"error": "Rota não encontrada."})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Usuário ou endereço IP já cadastrado."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            LOG.exception("POST %s falhou", path)
            self.send_json(500, {"error": str(exc)})

    def do_PUT(self):
        path = urlparse(self.path).path
        try:
            payload = self.body_json()
            user = self.require_user()
            if not user:
                return
            if path.startswith("/api/printers/") and path.endswith("/photo"):
                printer_id = int(path.split("/")[3])
                mime = str(payload.get("mime", ""))
                if mime not in ("image/png", "image/jpeg", "image/webp"):
                    raise ValueError("Use uma imagem PNG, JPEG ou WebP.")
                raw = base64.b64decode(payload.get("base64", ""), validate=True)
                if not raw or len(raw) > 5_000_000:
                    raise ValueError("A imagem deve ter até 5 MB.")
                from PIL import Image
                import io
                image = Image.open(io.BytesIO(raw))
                image.verify()
                with db_connect() as db:
                    cur = db.execute("UPDATE printers SET photo=?,photo_mime=? WHERE id=?", (raw, mime, printer_id))
                    if cur.rowcount == 0:
                        self.send_json(404, {"error": "Equipamento não encontrado."}); return
                self.send_json(200, {"ok": True}); return
            if path.startswith("/api/printers/"):
                printer_id = int(path.split("/")[3])
                alias = str(payload.get("alias", "")).strip(); ip = str(payload.get("ip", "")).strip()
                community = str(payload.get("community", "")).strip(); version = str(payload.get("version", "2c"))
                ipaddress.ip_address(ip)
                if not alias or not community or version not in ("1", "2c"):
                    raise ValueError("Informe nome, comunidade SNMP e versão 1 ou 2c.")
                with db_connect() as db:
                    cur = db.execute("UPDATE printers SET alias=?,ip=?,community=?,version=? WHERE id=?", (alias, ip, community, version, printer_id))
                    if cur.rowcount == 0:
                        self.send_json(404, {"error": "Equipamento não encontrado."}); return
                self.send_json(200, {"ok": True}); return
            if path.startswith("/api/users/"):
                user_id = int(path.split("/")[3])
                password = str(payload.get("password", ""))
                salt, digest = hash_password(password)
                with db_connect() as db:
                    cur = db.execute("UPDATE users SET salt=?,password_hash=?,active=? WHERE id=?", (salt, digest, int(bool(payload.get("active", True))), user_id))
                    if cur.rowcount == 0:
                        self.send_json(404, {"error": "Usuário não encontrado."}); return
                self.send_json(200, {"ok": True}); return
            if path == "/api/settings":
                backup_path = str(payload.get("backup_path", "")).strip()
                retention = max(1, min(3650, int(payload.get("backup_retention_days", 30))))
                set_setting("backup_path", backup_path)
                set_setting("backup_retention_days", str(retention))
                self.send_json(200, {"ok": True}); return
            if path.startswith("/api/alerts/") and path.endswith("/ack"):
                alert_id = int(path.split("/")[3])
                with db_connect() as db:
                    db.execute("UPDATE alerts SET acknowledged_by=?,acknowledged_at=? WHERE id=?", (user["username"], iso_now(), alert_id))
                self.send_json(200, {"ok": True}); return
            self.send_json(404, {"error": "Rota não encontrada."})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "O endereço IP já está cadastrado."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            LOG.exception("PUT %s falhou", path)
            self.send_json(500, {"error": str(exc)})

    def do_DELETE(self):
        path = urlparse(self.path).path
        user = self.require_user()
        if not user:
            return
        try:
            if path.startswith("/api/printers/"):
                printer_id = int(path.split("/")[3])
                with db_connect() as db:
                    cur = db.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                self.send_json(200 if cur.rowcount else 404, {"ok": bool(cur.rowcount)}); return
            if path.startswith("/api/users/"):
                user_id = int(path.split("/")[3])
                with db_connect() as db:
                    total = db.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
                    if total <= 1:
                        self.send_json(400, {"error": "Não é possível remover a última conta ativa."}); return
                    cur = db.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
                    db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                self.send_json(200 if cur.rowcount else 404, {"ok": bool(cur.rowcount)}); return
            self.send_json(404, {"error": "Rota não encontrada."})
        except Exception as exc:
            LOG.exception("DELETE %s falhou", path)
            self.send_json(500, {"error": str(exc)})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    cert, key, fingerprint = build_certificate()
    ip = local_ip()
    INFO_PATH.write_text(f"URL: https://{ip}:{PORT}\nSHA256 do certificado: {fingerprint}\n", encoding="utf-8")
    stop = threading.Event()
    poller = threading.Thread(target=poller_loop, args=(stop,), daemon=True, name="snmp-poller")
    poller.start()
    httpd = ThreadingHTTPServer((HOST, PORT), ApiHandler)
    httpd.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    print("\nServiço central de Contadores de Impressoras iniciado.")
    print(f"Acesso: https://{ip}:{PORT}")
    print(f"Impressão digital SHA256 do certificado: {fingerprint}")
    print(f"Dados do servidor: {APP_DIR}")
    print("Deixe esta janela aberta para manter a coleta SNMP e o backup diário.\n")
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
