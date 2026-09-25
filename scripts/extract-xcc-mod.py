#!/usr/bin/env python3
"""
Extract the embedded XCC Mod Launcher (XMLF/XIF) payload from an old XCC
self-contained mod EXE.  This does NOT activate/install the mod.

It writes:
  embedded.xmlf
  inventory.json
  raw/<category>/<filename>

The raw files are exactly the payload stored by XCC. Some entries can use
XCC-specific encodings (diff/shp/vxl); inventory.json records the encoding so
we can decide how to reconstruct the final RA2 files safely.
"""

from __future__ import annotations

import argparse
import bz2
import json
import struct
import zlib
from collections import Counter
from pathlib import Path


FILE_ID = 0x1A464958  # b"XIF\x1a" little-endian

VT_BIN32 = 0
VT_BINARY = 1
VT_INT32 = 2
VT_STRING = 3
VT_EXTERNAL_BINARY = 4
VT_FLOAT = 5

VALUE_NAMES = {
    0: "cx",
    1: "cy",
    2: "c_frames",
    3: "fname",
    4: "ft",
    5: "fdata",
    6: "encoding",
    7: "name",
    8: "mail",
    9: "link_title",
    10: "link",
    11: "game",
    12: "mod_name",
    13: "csf_diff_compression",
    14: "ini_diff_compression",
    15: "custom_button_text",
    16: "exit_button",
    17: "manual_button",
    18: "site_button",
    19: "update_button",
    20: "xhp_button",
    21: "mod_version",
    22: "mod_ucf",
    23: "confirm_deactivate",
    24: "mf_version",
    25: "shp_compression",
    26: "vxl_compression",
    27: "cb_d",
    28: "mode",
    29: "module",
    30: "mod_mfs",
}

CATEGORY_NAMES = [
    "cameo", "hva", "ini", "map", "mix", "screen", "shp", "sound",
    "speech", "string-table", "theme", "video", "vxl", "launcher",
    "manual", "interface", "tmp", "side-1", "side-2", "side-3",
]

ENCODING_NAMES = {
    0: "none",
    1: "diff",
    2: "jpeg",
    3: "mng",
    4: "mpeg",
    5: "ogg",
    6: "png",
    7: "shp",
    8: "vxl",
}


class ParseError(RuntimeError):
    pass


class Cursor:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def need(self, n: int) -> None:
        if self.pos + n > len(self.data):
            raise ParseError(
                f"Unexpected EOF at 0x{self.pos:x}: need {n} bytes, "
                f"have {len(self.data) - self.pos}"
            )

    def u8(self) -> int:
        self.need(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def i32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def f32(self) -> float:
        self.need(4)
        v = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return v

    def take(self, n: int) -> bytes:
        if n < 0:
            raise ParseError(f"Negative size {n} at 0x{self.pos:x}")
        self.need(n)
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v


def is_old_string(data: bytes) -> bool:
    if not data or data[-1] != 0:
        return False
    for b in data[:-1]:
        if b != 9 and b < 0x20:
            return False
    return True


def old_value(raw: bytes) -> dict:
    if is_old_string(raw):
        return {"type": VT_STRING, "data": raw}
    if len(raw) == 4:
        return {
            "type": VT_INT32,
            "int": struct.unpack("<i", raw)[0],
            "data": raw,
        }
    return {"type": VT_BINARY, "data": raw}


def parse_key_old(cur: Cursor) -> dict:
    node = {"keys": {}, "values": {}}

    key_count = cur.i32()
    if key_count < 0 or key_count > 1_000_000:
        raise ParseError(f"Invalid old key count: {key_count}")
    for _ in range(key_count):
        kid = cur.i32()
        node["keys"][kid] = parse_key_old(cur)

    value_count = cur.i32()
    if value_count < 0 or value_count > 1_000_000:
        raise ParseError(f"Invalid old value count: {value_count}")
    for _ in range(value_count):
        vid = cur.i32()
        size = cur.i32()
        node["values"][vid] = old_value(cur.take(size))

    return node


def parse_value_new(cur: Cursor) -> dict:
    vt = cur.u8()
    if vt == VT_BIN32:
        return {"type": vt, "int": cur.u32()}
    if vt == VT_INT32:
        return {"type": vt, "int": cur.i32()}
    if vt == VT_FLOAT:
        return {"type": vt, "float": cur.f32()}
    if vt == VT_EXTERNAL_BINARY:
        size = cur.i32()
        if size < 0:
            raise ParseError(f"Invalid external value size: {size}")
        return {"type": vt, "external_size": size, "data": None}

    size = cur.i32()
    return {"type": vt, "data": cur.take(size)}


def parse_key_new(cur: Cursor) -> dict:
    node = {"keys": {}, "values": {}}

    key_count = cur.i32()
    if key_count < 0 or key_count > 1_000_000:
        raise ParseError(f"Invalid new key count: {key_count}")
    kid = 0
    for _ in range(key_count):
        kid += cur.i32()
        node["keys"][kid] = parse_key_new(cur)

    value_count = cur.i32()
    if value_count < 0 or value_count > 1_000_000:
        raise ParseError(f"Invalid new value count: {value_count}")
    vid = 0
    for _ in range(value_count):
        vid += cur.i32()
        node["values"][vid] = parse_value_new(cur)

    return node


def load_external(node: dict, cur: Cursor) -> None:
    # Matches Cxif_key::load_external: child keys first, then values.
    for kid in sorted(node["keys"]):
        load_external(node["keys"][kid], cur)
    for vid in sorted(node["values"]):
        value = node["values"][vid]
        if value.get("type") == VT_EXTERNAL_BINARY:
            size = value["external_size"]
            value["data"] = cur.take(size)


def parse_xif(data: bytes) -> tuple[dict, dict]:
    if len(data) < 8:
        raise ParseError("XIF payload is too small")

    file_id, version = struct.unpack_from("<ii", data, 0)
    if file_id != FILE_ID:
        raise ParseError(
            f"Bad XIF id: 0x{file_id & 0xffffffff:08x}; expected 0x{FILE_ID:08x}"
        )

    info = {"version": version, "size": len(data)}

    if version == 0:
        # XCC old format starts the key body at offset 8.
        cur = Cursor(data, 8)
        root = parse_key_old(cur)
        if cur.pos != len(data):
            raise ParseError(
                f"Old XIF trailing data: parsed {cur.pos}, total {len(data)}"
            )
        return root, info

    if version not in (1, 2):
        raise ParseError(f"Unsupported XIF version: {version}")

    if len(data) < 12:
        raise ParseError("Truncated XIF header")
    size_uncompressed = struct.unpack_from("<i", data, 8)[0]
    info["size_uncompressed"] = size_uncompressed

    if version == 1:
        if size_uncompressed:
            packed = data[12:]
            decoded = zlib.decompress(packed)
            if len(decoded) != size_uncompressed:
                raise ParseError(
                    f"XIF v1 decoded size mismatch: {len(decoded)} != "
                    f"{size_uncompressed}"
                )
            cur = Cursor(decoded)
            root = parse_key_new(cur)
            if cur.pos != len(decoded):
                raise ParseError("XIF v1 decoded structure has trailing bytes")
            return root, info

        cur = Cursor(data, 12)
        root = parse_key_new(cur)
        load_external(root, cur)
        if cur.pos != len(data):
            raise ParseError("XIF v1 structure has trailing bytes")
        return root, info

    # version 2 / fast
    if len(data) < 20:
        raise ParseError("Truncated XIF v2 header")
    size_compressed, size_external = struct.unpack_from("<ii", data, 12)
    info["size_compressed"] = size_compressed
    info["size_external"] = size_external

    if size_uncompressed:
        start = 20
        packed = data[start:start + size_compressed]
        if len(packed) != size_compressed:
            raise ParseError("Truncated compressed XIF body")
        if packed.startswith(b"BZh"):
            decoded = bz2.decompress(packed)
            info["compression"] = "bzip2"
        else:
            decoded = zlib.decompress(packed)
            info["compression"] = "zlib"
        if len(decoded) != size_uncompressed:
            raise ParseError(
                f"XIF v2 decoded size mismatch: {len(decoded)} != "
                f"{size_uncompressed}"
            )
        cur = Cursor(decoded)
        root = parse_key_new(cur)
        if cur.pos != len(decoded):
            raise ParseError("XIF v2 decoded structure has trailing bytes")

        ext_cur = Cursor(data, start + size_compressed)
        load_external(root, ext_cur)
        if ext_cur.pos != len(data):
            raise ParseError(
                f"XIF v2 external/trailing size mismatch: parsed "
                f"{ext_cur.pos}, total {len(data)}"
            )
        return root, info

    cur = Cursor(data, 20)
    root = parse_key_new(cur)
    load_external(root, cur)
    if cur.pos != len(data):
        raise ParseError("XIF v2 uncompressed structure has trailing bytes")
    return root, info


def value_bytes(value: dict | None) -> bytes | None:
    if not value:
        return None
    if "data" in value:
        return value["data"]
    if value.get("type") in (VT_BIN32, VT_INT32):
        return struct.pack("<i", int(value["int"]))
    if value.get("type") == VT_FLOAT:
        return struct.pack("<f", float(value["float"]))
    return None


def value_int(node: dict, vid: int, default=None):
    value = node["values"].get(vid)
    if value is None:
        return default
    if "int" in value:
        return int(value["int"])
    raw = value_bytes(value)
    if raw is not None and len(raw) == 4:
        return struct.unpack("<i", raw)[0]
    return default


def value_string(node: dict, vid: int, default=""):
    value = node["values"].get(vid)
    if value is None:
        return default
    raw = value_bytes(value)
    if raw is None:
        return default
    raw = raw.split(b"\0", 1)[0]
    for enc in ("utf-8", "cp1252", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1", errors="replace")


def safe_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    if not name or name in (".", ".."):
        raise ParseError(f"Unsafe/empty embedded filename: {name!r}")
    return name


def extract_embedded_xif(exe: bytes) -> bytes:
    if len(exe) < 12:
        raise ParseError("EXE is too small")
    cb_mod = struct.unpack_from("<i", exe, len(exe) - 4)[0]
    if cb_mod <= 4 or cb_mod + 4 >= len(exe):
        raise ParseError(
            "No valid appended XCC mod size marker found at end of EXE"
        )
    start = len(exe) - 4 - cb_mod
    payload = exe[start:start + cb_mod]
    if payload[:4] != b"XIF\x1a":
        raise ParseError(
            f"Appended payload does not start with XIF\\x1a "
            f"(offset 0x{start:x})"
        )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe", type=Path, help="Self-contained XCC Mod Launcher EXE")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: <exe-dir>/xcc-extracted)",
    )
    args = ap.parse_args()

    exe_path = args.exe.resolve()
    out = (
        args.out.resolve()
        if args.out
        else (exe_path.parent / "xcc-extracted").resolve()
    )
    out.mkdir(parents=True, exist_ok=True)

    exe = exe_path.read_bytes()
    xif = extract_embedded_xif(exe)
    (out / "embedded.xmlf").write_bytes(xif)

    root, xif_info = parse_xif(xif)

    meta = {
        "author": value_string(root, 7),
        "mail": value_string(root, 8),
        "link_title": value_string(root, 9),
        "link": value_string(root, 10),
        "game": value_int(root, 11),
        "mod_name": value_string(root, 12),
        "mod_version": value_string(root, 21),
        "mf_version": value_int(root, 24),
        "mod_mfs": value_string(root, 30, "98"),
    }

    inventory = []
    raw_root = out / "raw"

    for category_id in sorted(root["keys"]):
        if category_id >= len(CATEGORY_NAMES):
            continue
        category_name = CATEGORY_NAMES[category_id]
        category = root["keys"][category_id]

        for entry_id in sorted(category["keys"]):
            entry = category["keys"][entry_id]
            fname = value_string(entry, 3)
            if not fname:
                continue
            encoding_id = value_int(entry, 6, 0)
            fdata = value_bytes(entry["values"].get(5))
            record = {
                "category_id": category_id,
                "category": category_name,
                "entry_id": entry_id,
                "filename": fname,
                "file_type": value_int(entry, 4),
                "encoding_id": encoding_id,
                "encoding": ENCODING_NAMES.get(
                    encoding_id, f"unknown-{encoding_id}"
                ),
                "payload_size": len(fdata) if fdata is not None else None,
                "decoded_size_hint": value_int(entry, 27),
                "mode": value_int(entry, 28, -1),
                "module": value_int(entry, 29, -1),
            }
            inventory.append(record)

            if fdata is not None:
                dst_dir = raw_root / category_name
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst = dst_dir / safe_name(fname)
                if dst.exists():
                    raise ParseError(f"Duplicate output filename: {dst}")
                dst.write_bytes(fdata)

    report = {
        "source_exe": str(exe_path),
        "xif": xif_info,
        "metadata": meta,
        "files": inventory,
    }
    (out / "inventory.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    category_counts = Counter(x["category"] for x in inventory)
    encoding_counts = Counter(x["encoding"] for x in inventory)

    print("XCC MOD EXTRACTED")
    print(f"Source:      {exe_path}")
    print(f"Output:      {out}")
    print(f"XIF version: {xif_info['version']}")
    print(f"Mod:         {meta['mod_name'] or '(unknown)'}")
    print(f"Version:     {meta['mod_version'] or '(unknown)'}")
    print(f"Game ID:     {meta['game']}")
    print(f"MFS:         {meta['mod_mfs'] or '(default 98)'}")
    print(f"Files:       {len(inventory)}")
    print()
    print("Categories:")
    for name, count in sorted(category_counts.items()):
        print(f"  {name:14} {count}")
    print()
    print("Encodings:")
    for name, count in sorted(encoding_counts.items()):
        print(f"  {name:14} {count}")
    print()
    print("Inventory:")
    for item in inventory:
        size = item["payload_size"]
        size_s = "-" if size is None else str(size)
        print(
            f"  [{item['category']}] {item['filename']} "
            f"encoding={item['encoding']} size={size_s}"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ParseError, zlib.error, OSError) as exc:
        raise SystemExit(f"ERROR: {exc}")
