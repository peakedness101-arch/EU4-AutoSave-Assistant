from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path

from .models import (
    ArmySnapshot,
    CountrySnapshot,
    LoanSnapshot,
    PlayerCountry,
    SaveRecord,
)


class SaveParseError(ValueError):
    pass


_TAG_RE = re.compile(rb"^[A-Z0-9]{3}$")
_BRACE_OR_QUOTE_RE = re.compile(rb'[{}"]')
_COUNTRY_HEADER_RE = re.compile(rb"(?m)^\t([A-Z0-9]{3})=\{")
_PROVINCE_HEADER_RE = re.compile(rb"(?m)^-?(\d+)=\{")
_TOP_LEVEL_BOUNDARIES = {
    # Stable in EU4 1.37.5 (491d). Unknown layouts use the generic scanner.
    b"countries": (b"\nactive_advisors={",),
}


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _decode_player_name(value: bytes) -> str:
    if any(byte < 0x20 or byte == 0x7F for byte in value):
        return f"ID:{value.hex()}"
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("utf-8", errors="backslashreplace")


def _matching_brace(data: bytes, open_index: int, limit: int | None = None) -> int:
    end = len(data) if limit is None else limit
    depth = 0
    quoted = False
    for match in _BRACE_OR_QUOTE_RE.finditer(data, open_index, end):
        token = match.start()
        value = data[token]
        if value == 0x22:
            slashes = 0
            back = token - 1
            while back >= open_index and data[back] == 0x5C:
                slashes += 1
                back -= 1
            if slashes % 2 == 0:
                quoted = not quoted
            continue
        if quoted:
            continue
        depth += 1 if value == 0x7B else -1
        if depth == 0:
            return token + 1
    if quoted:
        raise SaveParseError("存档块中的字符串引号不完整。")
    raise SaveParseError("存档块的花括号不完整。")


def _block_at(data: bytes, marker_start: int, limit: int | None = None) -> bytes:
    open_index = data.find(b"{", marker_start, len(data) if limit is None else limit)
    if open_index < 0:
        raise SaveParseError("找到字段但没有找到块起始花括号。")
    close_index = _matching_brace(data, open_index, limit)
    return data[marker_start:close_index]


def _top_level_range(data: bytes, key: bytes) -> tuple[int, int]:
    match = re.search(rb"(?m)^" + re.escape(key) + rb"=\{", data)
    if not match:
        raise SaveParseError(f"存档缺少顶层 {key.decode(errors='replace')} 块。")
    for marker in _TOP_LEVEL_BOUNDARIES.get(key, ()):
        boundary = data.find(marker, match.end())
        if boundary >= 0 and data[boundary - 1 : boundary] == b"}":
            return match.start(), boundary
    open_index = data.find(b"{", match.start())
    return match.start(), _matching_brace(data, open_index)


def _top_level_block(data: bytes, key: bytes) -> bytes:
    start, end = _top_level_range(data, key)
    return data[start:end]


def _direct_block(data: bytes, key: bytes, indent: int) -> bytes | None:
    marker = b"\n" + (b"\t" * indent) + key + b"={"
    start = data.find(marker)
    if start < 0:
        if data.startswith((b"\t" * indent) + key + b"={"):
            start = 0
        else:
            return None
    return _block_at(data, start)


def _direct_blocks(data: bytes, key: bytes, indent: int) -> list[bytes]:
    marker = b"\n" + (b"\t" * indent) + key + b"={"
    result: list[bytes] = []
    cursor = 0
    while True:
        start = data.find(marker, cursor)
        if start < 0:
            break
        block = _block_at(data, start)
        result.append(block)
        cursor = start + len(block)
    return result


def _scalar_bytes(data: bytes, key: bytes, indent: int) -> bytes | None:
    direct = (b"\t" * indent) + key + b"="
    marker = b"\n" + direct
    start = data.find(marker)
    if start >= 0:
        start += len(marker)
    elif data.startswith(direct):
        start = len(direct)
    else:
        return None
    end = data.find(b"\n", start)
    if end < 0:
        end = len(data)
    value = data[start:end].strip()
    if len(value) >= 2 and value.startswith(b'"') and value.endswith(b'"'):
        value = value[1:-1]
    return value


def _float_value(data: bytes, key: bytes, indent: int, default: float = 0.0) -> float:
    value = _scalar_bytes(data, key, indent)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_value(data: bytes, key: bytes, indent: int, default: int = 0) -> int:
    return int(_float_value(data, key, indent, float(default)))


def _string_value(data: bytes, key: bytes, indent: int, default: str = "") -> str:
    value = _scalar_bytes(data, key, indent)
    return _decode(value) if value is not None else default


def _number_list(block: bytes) -> list[float]:
    open_index = block.find(b"{")
    close_index = block.rfind(b"}")
    if open_index < 0 or close_index < 0:
        return []
    return [float(x) for x in re.findall(rb"-?\d+(?:\.\d+)?", block[open_index + 1 : close_index])]


def _read_container(path: Path) -> tuple[str, bytes, bytes, str]:
    if not path.is_file():
        raise SaveParseError(f"存档不存在：{path}")
    raw = path.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    source = io.BytesIO(raw)
    if zipfile.is_zipfile(source):
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
            if "gamestate" not in names or "meta" not in names:
                raise SaveParseError("ZIP 存档缺少 gamestate 或 meta。")
            return "zip", archive.read("gamestate"), archive.read("meta"), fingerprint
    if not raw.startswith(b"EU4txt"):
        raise SaveParseError("不支持的存档格式；期望 EU4txt 或 EU4 ZIP。")
    return "plaintext", raw, raw, fingerprint


def _parse_players(gamestate: bytes) -> list[PlayerCountry]:
    block = _top_level_block(gamestate, b"players_countries")
    values = re.findall(rb'"([^"\r\n]*)"', block)
    players: list[PlayerCountry] = []
    for index in range(0, len(values) - 1, 2):
        name, tag = values[index], values[index + 1]
        if _TAG_RE.match(tag):
            players.append(PlayerCountry(_decode_player_name(name), tag.decode("ascii")))
    return players


def _parse_province_state(gamestate: bytes) -> tuple[dict[int, str], dict[int, str]]:
    """Read current province ownership/control without parsing nested history.

    EU4 serializes province ids as negative top-level keys in 1.37 saves.  The
    current owner is a direct child of that block (two tabs); historical owner
    entries are more deeply indented and must not be mistaken for current state.
    """
    marker = re.search(rb"(?m)^provinces=\{", gamestate)
    if marker is None:
        return {}, {}
    # In EU4 1.37 the next large top-level block is countries.  Slicing at its
    # marker avoids a byte-by-byte brace walk across tens of megabytes.
    countries_start = gamestate.find(b"\ncountries={", marker.end())
    if countries_start >= 0:
        province_start, province_end = marker.end(), countries_start
    else:
        try:
            province_start, province_end = marker.end(), _matching_brace(
                gamestate, gamestate.find(b"{", marker.start())
            )
        except SaveParseError:
            return {}, {}
    matches = list(_PROVINCE_HEADER_RE.finditer(gamestate, province_start, province_end))
    owners: dict[int, str] = {}
    controllers: dict[int, str] = {}
    for index, match in enumerate(matches):
        province_id = int(match.group(1))
        if province_id <= 0:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else province_end
        owner = re.search(
            rb'(?m)^\t\towner="?([A-Z0-9]{3})"?\s*$',
            gamestate[match.end() : end],
        )
        if owner:
            owners[province_id] = owner.group(1).decode("ascii")
        controller = re.search(
            rb'(?m)^\t\tcontroller="?([A-Z0-9]{3})"?\s*$',
            gamestate[match.end() : end],
        )
        if controller:
            controllers[province_id] = controller.group(1).decode("ascii")
    return owners, controllers


INCOME_KEYS = (
    "taxation", "production", "trade", "gold", "tariffs", "vassals",
    "harbor_fees", "subsidies", "war_reparations", "interest", "gifts",
    "events", "spoils_of_war", "treasure_fleet", "siphoning_income",
    "condottieri", "knowledge_sharing", "blockading_foreign_ports",
    "looting_foreign_cities",
)

EXPENSE_INDEX = {
    "advisor_maintenance": 0, "interest": 1, "state_maintenance": 2,
    "subsidies": 4, "war_reparations": 5, "army_maintenance": 6,
    "fleet_maintenance": 7, "fort_maintenance": 8, "colonists": 9,
    "missionaries": 10, "raising_armies": 11, "building_fleets": 12,
    "building_fortresses": 13, "buildings": 14, "repaid_loans": 16,
    "gifts": 17, "advisors": 18, "events": 19, "peace": 20,
    "vassal_fee": 21, "tariffs": 22, "support_loyalists": 23,
    "condottieri": 26, "root_out_corruption": 27,
    "embrace_institution": 28, "knowledge_sharing": 30,
    "trade_company_investments": 31, "ports_blockaded": 33,
    "cities_looted": 34, "monuments": 35, "cot_upgrades": 36,
    "colony_changes": 37,
}

MANA_COMMON_INDEX = {
    0: "buy_idea", 1: "advance_tech", 2: "boost_stab", 3: "buy_general",
    4: "buy_admiral", 5: "buy_conq", 6: "buy_explorer", 7: "develop_prov",
    8: "force_march", 9: "assault", 10: "seize_colony", 11: "burn_colony",
    12: "attack_natives", 13: "scorch_earth", 14: "demand_non_wargoal_prov",
    15: "reduce_inflation", 16: "move_capital", 17: "make_province_core",
    18: "replace_rival", 19: "change_gov", 20: "change_culture",
    21: "harsh_treatment", 22: "reduce_we", 23: "boost_faction",
    24: "raise_war_taxes",
}


def _mana_index_mapping(game_version_second: int | None) -> dict[int, str]:
    """Return EU4's version-dependent ``*_spent_indexed`` category mapping."""
    mapping = dict(MANA_COMMON_INDEX)
    if game_version_second is None or game_version_second >= 35:
        mapping.update({
            25: "increse_tariffs", 26: "promote_merc", 27: "decrease_tariffs",
            28: "move_trade_port", 29: "create_trade_post", 30: "siege_sorties",
            31: "buy_religious_reform", 32: "set_primary_culture",
            33: "add_accepted_culture", 34: "remove_accepted_culture",
            35: "strengthen_government", 36: "other", 37: "artillery_barrage",
            38: "establish_siberian_frontier", 39: "other", 40: "naval_barrage",
            41: "add_tribal_land", 42: "other", 43: "force_march",
            44: "create_leader", 45: "enforce_culture", 46: "effect",
            47: "minority_expulsion", 48: "other", 49: "other", 50: "other",
        })
    elif game_version_second >= 31:
        mapping.update({
            25: "increse_tariffs", 26: "promote_merc", 27: "decrease_tariffs",
            28: "move_trade_port", 29: "create_trade_post", 30: "siege_sorties",
            31: "buy_religious_reform", 32: "set_primary_culture",
            33: "add_accepted_culture", 34: "remove_accepted_culture",
            35: "strengthen_government", 36: "boost_militarization", 37: "other",
            38: "artillery_barrage", 39: "establish_siberian_frontier",
            40: "government_interaction", 41: "other", 42: "naval_barrage",
            43: "add_tribal_land", 44: "other", 45: "force_march",
            46: "create_leader", 47: "enforce_culture", 48: "effect",
            49: "minority_expulsion", 50: "other",
        })
    else:
        mapping.update({
            25: "buy_native_advancement", 26: "increse_tariffs",
            27: "promote_merc", 28: "decrease_tariffs", 29: "move_trade_port",
            30: "create_trade_post", 31: "siege_sorties",
            32: "buy_religious_reform", 33: "set_primary_culture",
            34: "add_accepted_culture", 35: "remove_accepted_culture",
            36: "strengthen_government", 37: "boost_militarization", 38: "other",
            39: "artillery_barrage", 40: "establish_siberian_frontier",
            41: "government_interaction", 42: "other", 43: "naval_barrage",
            44: "other", 45: "force_march", 46: "create_leader",
            47: "enforce_culture", 48: "effect", 49: "minority_expulsion",
            50: "other",
        })
    return mapping


def _indexed_numbers(block: bytes | None) -> dict[int, int]:
    if not block:
        return {}
    result: dict[int, int] = {}
    # EU4 commonly serializes several index/value pairs on one physical line.
    # Anchoring this match to the start of a line silently kept only the first.
    for match in re.finditer(rb"(?<![A-Za-z0-9_])(\d+)=(-?\d+)", block):
        index, value = int(match.group(1)), int(match.group(2))
        result[index] = result.get(index, 0) + value
    return result


def _mana_breakdown(
    country: bytes, game_version_second: int | None = None
) -> dict[str, dict[str, int]]:
    mapping = _mana_index_mapping(game_version_second)
    result: dict[str, dict[str, int]] = {}
    for power in ("adm", "dip", "mil"):
        values = _indexed_numbers(
            _direct_block(country, f"{power}_spent_indexed".encode(), 2)
        )
        breakdown: dict[str, int] = {}
        for index, value in values.items():
            if not value:
                continue
            key = mapping.get(index, f"unknown_{index}")
            breakdown[key] = breakdown.get(key, 0) + value
        result[power] = breakdown
    return result


def _parse_loans(country: bytes) -> list[LoanSnapshot]:
    loans: list[LoanSnapshot] = []
    for block in _direct_blocks(country, b"loan", 2):
        loans.append(
            LoanSnapshot(
                amount=_float_value(block, b"amount", 3),
                annual_interest=_float_value(block, b"interest", 3),
                estate_loan=_string_value(block, b"estate_loan", 3).lower() == "yes",
                expiry_date=_string_value(block, b"expiry_date", 3) or None,
            )
        )
    return loans


def _parse_armies(country: bytes) -> list[ArmySnapshot]:
    armies: list[ArmySnapshot] = []
    for sequence, block in enumerate(_direct_blocks(country, b"army", 2), start=1):
        id_block = _direct_block(block, b"id", 3)
        numeric_id = _int_value(id_block or b"", b"id", 4, sequence)
        id_type = _int_value(id_block or b"", b"type", 4, 0)
        army_id = f"{id_type}:{numeric_id}:{sequence}"
        unit_types: dict[str, int] = {}
        strength = 0.0
        regiments = _direct_blocks(block, b"regiment", 3)
        for regiment in regiments:
            unit_type = _string_value(regiment, b"type", 4, "unknown")
            unit_types[unit_type] = unit_types.get(unit_type, 0) + 1
            strength += _float_value(regiment, b"strength", 4, 1.0) * 1000.0
        location = _int_value(block, b"location", 3, -1)
        armies.append(
            ArmySnapshot(
                army_id=army_id,
                name=_string_value(block, b"name", 3, f"Army {sequence}"),
                location=location if location >= 0 else None,
                regiment_count=len(regiments),
                strength=strength,
                unit_types=unit_types,
            )
        )
    return armies


def _parse_ship_count(country: bytes) -> int:
    return sum(
        len(_direct_blocks(navy, b"ship", 3))
        for navy in _direct_blocks(country, b"navy", 2)
    )


def parse_country_block(
    tag: str,
    block: bytes,
    player_name: str | None = None,
    game_version_second: int | None = None,
) -> CountrySnapshot:
    ledger = _direct_block(block, b"ledger", 2) or b""
    expense_table = _direct_block(ledger, b"lastmonthexpensetable", 3)
    expenses = _number_list(expense_table) if expense_table else []
    income_table = _direct_block(ledger, b"lastmonthincometable", 3)
    incomes = _number_list(income_table) if income_table else []
    income_breakdown = {
        key: max(0.0, incomes[index])
        for index, key in enumerate(INCOME_KEYS)
        if index < len(incomes) and incomes[index] > 0
    }
    if len(incomes) > len(INCOME_KEYS):
        other_income = sum(max(0.0, value) for value in incomes[len(INCOME_KEYS) :])
        if other_income:
            income_breakdown["other"] = other_income
    expense_breakdown = {
        key: max(0.0, expenses[index])
        for key, index in EXPENSE_INDEX.items()
        if index < len(expenses) and expenses[index] > 0
    }
    known_expense_indices = set(EXPENSE_INDEX.values())
    other_expense = sum(
        max(0.0, value)
        for index, value in enumerate(expenses)
        if index not in known_expense_indices
    )
    if other_expense:
        expense_breakdown["other"] = other_expense
    powers_block = _direct_block(block, b"powers", 2)
    powers = [int(x) for x in _number_list(powers_block)] if powers_block else []
    tech_block = _direct_block(block, b"technology", 2) or b""
    ideas_block = _direct_block(block, b"active_idea_groups", 2) or b""
    ideas = {
        match.group(1).decode("ascii", errors="replace"): int(match.group(2))
        for match in re.finditer(rb"(?m)^\t\t\t([A-Za-z0-9_]+)=(-?\d+)", ideas_block)
    }
    flags_block = _direct_block(block, b"flags", 2) or b""
    flags = {
        match.group(1).decode("utf-8", errors="replace")
        for match in re.finditer(rb"(?m)^\t\t\t([^\s=]+)=", flags_block)
    }
    variables_block = _direct_block(block, b"variables", 2) or b""
    variables = {
        match.group(1).decode("utf-8", errors="replace"): _decode(match.group(2).strip())
        for match in re.finditer(rb"(?m)^\t\t\t([^\s=]+)=([^\r\n]+)", variables_block)
    }
    estimated_loan = _float_value(block, b"estimated_loan", 2, -1.0)
    return CountrySnapshot(
        tag=tag,
        player_name=player_name,
        treasury=_float_value(block, b"treasury", 2),
        monthly_income=_float_value(ledger, b"lastmonthincome", 3),
        monthly_expense=_float_value(ledger, b"lastmonthexpense", 3),
        monthly_interest=expenses[1] if len(expenses) > 1 else 0.0,
        estimated_loan=estimated_loan if estimated_loan > 0 else None,
        powers=tuple((powers + [0, 0, 0])[:3]),
        technology=(
            _int_value(tech_block, b"adm_tech", 3),
            _int_value(tech_block, b"dip_tech", 3),
            _int_value(tech_block, b"mil_tech", 3),
        ),
        ideas=ideas,
        manpower=_float_value(block, b"manpower", 2),
        max_manpower=_float_value(block, b"max_manpower", 2),
        sailors=_float_value(block, b"sailors", 2),
        max_sailors=_float_value(block, b"max_sailors", 2),
        ship_count=_parse_ship_count(block),
        stability=_float_value(block, b"stability", 2),
        inflation=_float_value(block, b"inflation", 2),
        development=_float_value(block, b"development", 2),
        religion=_string_value(block, b"religion", 2),
        primary_culture=_string_value(block, b"primary_culture", 2),
        income_breakdown=income_breakdown,
        expense_breakdown=expense_breakdown,
        mana_spending=_mana_breakdown(block, game_version_second),
        loans=_parse_loans(block),
        armies=_parse_armies(block),
        flags=flags,
        variables=variables,
    )


def parse_save(path: str | Path, include_all_countries: bool = False) -> SaveRecord:
    save_path = Path(path)
    save_format, gamestate, meta, fingerprint = _read_container(save_path)
    version_source = meta if b"savegame_version=" in meta else gamestate
    version_fields = {
        key.decode("ascii"): int(value)
        for key, value in re.findall(
            rb"(?m)^\s*(first|second|third|forth|fourth)=(\d+)", version_source
        )
    }
    fourth = version_fields.get("forth", version_fields.get("fourth"))
    game_version = None
    if all(key in version_fields for key in ("first", "second", "third")) and fourth is not None:
        game_version = ".".join(
            str(value)
            for value in (
                version_fields["first"],
                version_fields["second"],
                version_fields["third"],
                fourth,
            )
        )
    players = _parse_players(gamestate)
    player_names_by_tag: dict[str, list[str]] = {}
    for entry in players:
        names = player_names_by_tag.setdefault(entry.country_tag, [])
        if entry.player_name not in names:
            names.append(entry.player_name)
    player_by_tag = {
        tag: " / ".join(names) for tag, names in player_names_by_tag.items()
    }
    countries_start, countries_end = _top_level_range(gamestate, b"countries")
    country_matches = list(
        _COUNTRY_HEADER_RE.finditer(gamestate, countries_start, countries_end)
    )
    countries: dict[str, CountrySnapshot] = {}
    wanted_tags = set(player_by_tag)
    countries_close = gamestate.rfind(b"}", countries_start, countries_end)
    for index, match in enumerate(country_matches):
        tag = match.group(1).decode("ascii")
        if not include_all_countries and tag not in wanted_tags:
            continue
        end = (
            country_matches[index + 1].start()
            if index + 1 < len(country_matches)
            else countries_close
        )
        block = gamestate[match.start() : end]
        countries[tag] = parse_country_block(
            tag,
            block,
            player_by_tag.get(tag),
            version_fields.get("second"),
        )

    game_date_match = re.search(rb"(?m)^date=([^\r\n]+)", meta)
    if not game_date_match:
        game_date_match = re.search(rb"(?m)^date=([^\r\n]+)", gamestate)
    local_player_match = re.search(rb"(?m)^player=\"?([A-Z0-9]{3})\"?", meta)
    multiplayer_match = re.search(rb"(?m)^multi_player=(yes|no)", meta)
    if not multiplayer_match:
        multiplayer_match = re.search(rb"(?m)^multi_player=(yes|no)", gamestate)
    fired_events: set[str] = set()
    try:
        fired_block = _top_level_block(gamestate, b"fired_events")
    except SaveParseError:
        pass
    else:
        body = fired_block[fired_block.find(b"{") + 1 : fired_block.rfind(b"}")]
        fired_events = {
            _decode(token.strip(b'"'))
            for token in re.findall(rb'"[^"\r\n]+"|[^\s{}]+', body)
            if token.strip(b'"')
        }

    province_owners, province_controllers = _parse_province_state(gamestate)
    return SaveRecord(
        path=save_path.resolve(),
        fingerprint=fingerprint,
        format=save_format,
        game_date=_decode(game_date_match.group(1).strip()) if game_date_match else "unknown",
        build_id=None,
        local_player_tag=(
            local_player_match.group(1).decode("ascii") if local_player_match else None
        ),
        players=players,
        countries=countries,
        game_version=game_version,
        multiplayer=(
            multiplayer_match.group(1) == b"yes" if multiplayer_match else None
        ),
        fired_events=fired_events,
        province_owners=province_owners,
        province_controllers=province_controllers,
    )
