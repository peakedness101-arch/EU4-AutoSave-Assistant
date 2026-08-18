from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .alerts import economic_alerts
from .models import CountrySnapshot, SaveRecord


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS saves (
    fingerprint TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    format TEXT NOT NULL,
    game_date TEXT NOT NULL,
    build_id TEXT,
    game_version TEXT,
    multiplayer INTEGER,
    local_player_tag TEXT,
    fired_events_json TEXT NOT NULL DEFAULT '[]',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS players (
    save_id TEXT NOT NULL REFERENCES saves(fingerprint) ON DELETE CASCADE,
    player_name TEXT NOT NULL,
    country_tag TEXT NOT NULL,
    PRIMARY KEY (save_id, player_name, country_tag)
);
CREATE TABLE IF NOT EXISTS countries (
    save_id TEXT NOT NULL REFERENCES saves(fingerprint) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    player_name TEXT,
    treasury REAL NOT NULL,
    monthly_income REAL NOT NULL,
    monthly_expense REAL NOT NULL,
    monthly_interest REAL NOT NULL,
    estimated_loan REAL,
    adm INTEGER NOT NULL,
    dip INTEGER NOT NULL,
    mil INTEGER NOT NULL,
    adm_tech INTEGER NOT NULL,
    dip_tech INTEGER NOT NULL,
    mil_tech INTEGER NOT NULL,
    ideas_json TEXT NOT NULL,
    manpower REAL NOT NULL,
    max_manpower REAL NOT NULL,
    sailors REAL NOT NULL DEFAULT 0,
    max_sailors REAL NOT NULL DEFAULT 0,
    ship_count INTEGER NOT NULL DEFAULT 0,
    stability REAL NOT NULL,
    inflation REAL NOT NULL,
    development REAL NOT NULL,
    flags_json TEXT NOT NULL DEFAULT '[]',
    variables_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (save_id, tag)
);
CREATE TABLE IF NOT EXISTS loans (
    save_id TEXT NOT NULL,
    country_tag TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    amount REAL NOT NULL,
    annual_interest REAL NOT NULL,
    estate_loan INTEGER NOT NULL,
    expiry_date TEXT,
    PRIMARY KEY (save_id, country_tag, sequence),
    FOREIGN KEY (save_id, country_tag) REFERENCES countries(save_id, tag) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS armies (
    save_id TEXT NOT NULL,
    country_tag TEXT NOT NULL,
    army_id TEXT NOT NULL,
    name TEXT NOT NULL,
    location INTEGER,
    regiment_count INTEGER NOT NULL,
    strength REAL NOT NULL,
    unit_types_json TEXT NOT NULL,
    PRIMARY KEY (save_id, country_tag, army_id),
    FOREIGN KEY (save_id, country_tag) REFERENCES countries(save_id, tag) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS alerts (
    save_id TEXT NOT NULL,
    country_tag TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    values_json TEXT NOT NULL,
    PRIMARY KEY (save_id, country_tag, code),
    FOREIGN KEY (save_id, country_tag) REFERENCES countries(save_id, tag) ON DELETE CASCADE
);
"""


class SaveDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._ensure_column("saves", "fired_events_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("saves", "game_version", "TEXT")
        self._ensure_column("saves", "multiplayer", "INTEGER")
        self._ensure_column("countries", "flags_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("countries", "variables_json", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column("countries", "sailors", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("countries", "max_sailors", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("countries", "ship_count", "INTEGER NOT NULL DEFAULT 0")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def import_record(self, record: SaveRecord) -> bool:
        exists = self.connection.execute(
            "SELECT 1 FROM saves WHERE fingerprint = ?", (record.fingerprint,)
        ).fetchone()
        if exists:
            self.connection.execute(
                "UPDATE saves SET path = ? WHERE fingerprint = ?",
                (str(record.path), record.fingerprint),
            )
            self.connection.commit()
            return False

        with self.connection:
            self.connection.execute(
                "INSERT INTO saves(fingerprint,path,format,game_date,build_id,game_version,multiplayer,"
                "local_player_tag,fired_events_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    record.fingerprint,
                    str(record.path),
                    record.format,
                    record.game_date,
                    record.build_id,
                    record.game_version,
                    None if record.multiplayer is None else int(record.multiplayer),
                    record.local_player_tag,
                    json.dumps(sorted(record.fired_events), ensure_ascii=False),
                ),
            )
            self.connection.executemany(
                "INSERT INTO players(save_id,player_name,country_tag) VALUES(?,?,?)",
                [
                    (record.fingerprint, player.player_name, player.country_tag)
                    for player in record.players
                ],
            )
            for country in record.countries.values():
                self._insert_country(record.fingerprint, country)
        return True

    def _insert_country(self, save_id: str, country: CountrySnapshot) -> None:
        self.connection.execute(
            "INSERT INTO countries("
            "save_id,tag,player_name,treasury,monthly_income,monthly_expense,monthly_interest,"
            "estimated_loan,adm,dip,mil,adm_tech,dip_tech,mil_tech,ideas_json,manpower,"
            "max_manpower,sailors,max_sailors,ship_count,stability,inflation,development,"
            "flags_json,variables_json"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                save_id,
                country.tag,
                country.player_name,
                country.treasury,
                country.monthly_income,
                country.monthly_expense,
                country.monthly_interest,
                country.estimated_loan,
                *country.powers,
                *country.technology,
                json.dumps(country.ideas, ensure_ascii=False),
                country.manpower,
                country.max_manpower,
                country.sailors,
                country.max_sailors,
                country.ship_count,
                country.stability,
                country.inflation,
                country.development,
                json.dumps(sorted(country.flags), ensure_ascii=False),
                json.dumps(country.variables, ensure_ascii=False),
            ),
        )
        self.connection.executemany(
            "INSERT INTO loans VALUES(?,?,?,?,?,?,?)",
            [
                (
                    save_id,
                    country.tag,
                    index,
                    loan.amount,
                    loan.annual_interest,
                    int(loan.estate_loan),
                    loan.expiry_date,
                )
                for index, loan in enumerate(country.loans)
            ],
        )
        self.connection.executemany(
            "INSERT INTO armies VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    save_id,
                    country.tag,
                    army.army_id,
                    army.name,
                    army.location,
                    army.regiment_count,
                    army.strength,
                    json.dumps(army.unit_types, ensure_ascii=False),
                )
                for army in country.armies
            ],
        )
        self.connection.executemany(
            "INSERT INTO alerts VALUES(?,?,?,?,?,?,?)",
            [
                (
                    save_id,
                    country.tag,
                    alert.code,
                    alert.severity,
                    alert.title,
                    alert.message,
                    json.dumps(alert.values, ensure_ascii=False),
                )
                for alert in economic_alerts(country)
            ],
        )

    def list_saves(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT fingerprint,path,game_date,game_version,multiplayer,local_player_tag,imported_at "
                "FROM saves ORDER BY imported_at DESC, game_date DESC"
            )
        )

    def list_countries(self, save_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT c.*, COALESCE(SUM(l.amount),0) AS total_debt, "
                "COUNT(l.sequence) AS loan_count, "
                "(SELECT COALESCE(SUM(a.strength),0) FROM armies a "
                " WHERE a.save_id=c.save_id AND a.country_tag=c.tag) AS army_strength "
                "FROM countries c LEFT JOIN loans l ON l.save_id=c.save_id AND l.country_tag=c.tag "
                "WHERE c.save_id=? GROUP BY c.save_id,c.tag ORDER BY c.tag",
                (save_id,),
            )
        )

    def list_alerts(self, save_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM alerts WHERE save_id=? ORDER BY country_tag,code", (save_id,)
            )
        )
