from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

import pefile


AUTOSAVE_PATTERN = re.compile(
    rb"\x48\x8b\x05(.{4})\x48\x8b\x88\x00\x1e\x00\x00"
    rb"\x48\x8b\x01\x45\x33\xc0\xb2\x01\xff\x90\x50\x01\x00\x00",
    re.DOTALL,
)
DATE_PATTERN = re.compile(
    rb"\x41\x8b\x3c\x24\x41\x89\xbe(.{4})"
    rb"\x41\x8b\x14\x24\x41\x89\x96(.{4})",
    re.DOTALL,
)
CLIENT_LOCAL_SAVE_RVA = 0x5CBEE0
CLIENT_LOCAL_SAVE_PROLOGUE = bytes.fromhex(
    "48 89 5c 24 10 48 89 74 24 18 48 89 4c 24 08 55"
)


def analyze(executable: Path) -> dict[str, object]:
    pe = pefile.PE(str(executable), fast_load=False)
    text = next(section for section in pe.sections if section.Name.rstrip(b"\0") == b".text")
    code = text.get_data()
    matches = list(AUTOSAVE_PATTERN.finditer(code))
    date_matches = list(DATE_PATTERN.finditer(code))
    result: dict[str, object] = {
        "executable": str(executable),
        "machine": hex(pe.FILE_HEADER.Machine),
        "autosave_signature_count": len(matches),
        "date_signature_count": len(date_matches),
        "client_local_save_rva": hex(CLIENT_LOCAL_SAVE_RVA),
        "client_local_save_prologue_match": (
            pe.get_data(CLIENT_LOCAL_SAVE_RVA, len(CLIENT_LOCAL_SAVE_PROLOGUE))
            == CLIENT_LOCAL_SAVE_PROLOGUE
        ),
    }
    if len(matches) == 1:
        match = matches[0]
        instruction_rva = text.VirtualAddress + match.start()
        displacement = struct.unpack("<i", match.group(1))[0]
        global_slot_rva = instruction_rva + 7 + displacement
        result.update(
            {
                "signature_rva": hex(instruction_rva),
                "global_slot_rva": hex(global_slot_rva),
                "service_offset": "0x1e00",
                "autosave_vtable_offset": "0x150",
            }
        )
    if len(date_matches) == 1:
        current_offset, derived_offset = (
            struct.unpack("<I", value)[0] for value in date_matches[0].groups()
        )
        result.update(
            {
                "current_date_offset": hex(current_offset),
                "derived_date_offset": hex(derived_offset),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    result = analyze(args.executable)
    print(json.dumps(result, indent=2))
    return 0 if (
        result["autosave_signature_count"] == 1
        and result["date_signature_count"] == 1
        and result["client_local_save_prologue_match"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
