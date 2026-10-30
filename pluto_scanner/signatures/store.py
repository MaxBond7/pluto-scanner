"""SQLite-backed local library of known signal signatures."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from ..paths import DATA_DIR
from .models import SignalSignature
from .seed import SEED_VERSION, seed_signatures

DEFAULT_DB = DATA_DIR / "signatures.db"


class SignatureStore:
    def __init__(self, path: str | Path | None = None, *, seed: bool = True) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        if seed:
            # Upsert built-ins so new catalog entries appear after an update.
            # User signatures have different ids and are never touched.
            self.seed_builtin()

    # ------------------------------------------------------------------ schema
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS signatures (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source_class TEXT NOT NULL,
                    start_hz REAL NOT NULL,
                    end_hz REAL NOT NULL,
                    bw_hz REAL NOT NULL DEFAULT 0,
                    modulation TEXT NOT NULL DEFAULT '',
                    duty REAL NOT NULL DEFAULT 0,
                    burst_ms REAL NOT NULL DEFAULT 0,
                    hop TEXT NOT NULL DEFAULT 'none',
                    notes TEXT NOT NULL DEFAULT '',
                    references_json TEXT NOT NULL DEFAULT '[]',
                    license TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    builtin INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("seed_version", str(SEED_VERSION)),
            )

    # -------------------------------------------------------------------- seed
    def seed_builtin(self) -> None:
        for signature in seed_signatures():
            signature.builtin = True
            self.upsert(signature)

    # -------------------------------------------------------------------- read
    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM signatures").fetchone()
        return int(row["n"]) if row else 0

    def all(self) -> list[SignalSignature]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signatures ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._row_to_sig(row) for row in rows]

    def search(self, query: str) -> list[SignalSignature]:
        query = (query or "").strip()
        if not query:
            return self.all()
        like = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signatures WHERE "
                "name LIKE ? OR category LIKE ? OR source_class LIKE ? "
                "OR modulation LIKE ? OR notes LIKE ? "
                "ORDER BY name COLLATE NOCASE",
                (like, like, like, like, like),
            ).fetchall()
        return [self._row_to_sig(row) for row in rows]

    def get(self, signature_id: str) -> SignalSignature | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM signatures WHERE id = ?", (signature_id,)
            ).fetchone()
        return self._row_to_sig(row) if row else None

    # ------------------------------------------------------------------- write
    def upsert(self, signature: SignalSignature) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signatures (
                    id, name, category, source_class, start_hz, end_hz, bw_hz,
                    modulation, duty, burst_ms, hop, notes, references_json,
                    license, confidence, builtin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    source_class=excluded.source_class,
                    start_hz=excluded.start_hz,
                    end_hz=excluded.end_hz,
                    bw_hz=excluded.bw_hz,
                    modulation=excluded.modulation,
                    duty=excluded.duty,
                    burst_ms=excluded.burst_ms,
                    hop=excluded.hop,
                    notes=excluded.notes,
                    references_json=excluded.references_json,
                    license=excluded.license,
                    confidence=excluded.confidence,
                    builtin=excluded.builtin
                """,
                (
                    signature.id,
                    signature.name,
                    signature.category,
                    signature.source_class,
                    float(signature.start_hz),
                    float(signature.end_hz),
                    float(signature.bw_hz),
                    signature.modulation,
                    float(signature.duty),
                    float(signature.burst_ms),
                    signature.hop,
                    signature.notes,
                    json.dumps(list(signature.references), ensure_ascii=False),
                    signature.license,
                    float(signature.confidence),
                    1 if signature.builtin else 0,
                ),
            )

    def delete(self, signature_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM signatures WHERE id = ?", (signature_id,)
            )
        return cursor.rowcount > 0

    # --------------------------------------------------------------- import/export
    def import_file(self, path: str | Path) -> int:
        path = Path(path)
        if path.suffix.lower() == ".csv":
            with path.open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            count = 0
            for row in rows:
                try:
                    self.upsert(SignalSignature.from_dict(row))
                    count += 1
                except Exception:
                    continue
            return count

        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            data = data.get("signatures", [])
        count = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                self.upsert(SignalSignature.from_dict(item))
                count += 1
            except Exception:
                continue
        return count

    def export_file(self, path: str | Path) -> Path:
        path = Path(path)
        signatures = self.all()
        if path.suffix.lower() == ".csv":
            fields = [
                "id", "name", "category", "source_class", "start_hz", "end_hz",
                "bw_hz", "modulation", "duty", "burst_ms", "hop", "notes",
                "references", "license", "confidence", "builtin",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for signature in signatures:
                    item = signature.to_dict()
                    item["references"] = "; ".join(signature.references)
                    writer.writerow({key: item.get(key, "") for key in fields})
        else:
            path.write_text(
                json.dumps(
                    {
                        "seed_version": SEED_VERSION,
                        "signatures": [sig.to_dict() for sig in signatures],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return path.resolve()

    # ------------------------------------------------------------------ helper
    @staticmethod
    def _row_to_sig(row: sqlite3.Row) -> SignalSignature:
        try:
            refs = json.loads(row["references_json"] or "[]")
        except Exception:
            refs = []
        return SignalSignature(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            source_class=row["source_class"],
            start_hz=float(row["start_hz"]),
            end_hz=float(row["end_hz"]),
            bw_hz=float(row["bw_hz"]),
            modulation=row["modulation"],
            duty=float(row["duty"]),
            burst_ms=float(row["burst_ms"]),
            hop=row["hop"],
            notes=row["notes"],
            references=[str(item) for item in refs],
            license=row["license"],
            confidence=float(row["confidence"]),
            builtin=bool(row["builtin"]),
        )
