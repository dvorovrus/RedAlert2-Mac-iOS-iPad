#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import plistlib
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_MOD_EXT = {
    ".mix", ".mmx", ".ini", ".csf", ".mpr", ".map", ".pkt", ".png", ".webm",
    ".bag", ".idx",
}

@dataclass
class ModSpec:
    mod_id: str
    root: Path
    files: list[Path]
    skipped: list[Path]
    meta: bytes

def die(msg: str) -> None:
    print(f"\nОШИБКА: {msg}", file=sys.stderr)
    raise SystemExit(1)

def norm(s: str) -> str:
    return s.replace("\\", "/")

def slugify(value: str) -> str:
    value = value.strip().lower().replace(" ", "-")
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-_")
    if not value:
        die("Не удалось определить ID мода")
    return value

def parse_general_ini(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    section = ""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section == "general" and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip().lower()] = value.split(";", 1)[0].strip()
    return out

def find_app_root(names: list[str]) -> str:
    roots = sorted({
        "/".join(n.split("/")[:2]) + "/"
        for n in names
        if n.startswith("Payload/") and ".app/" in n
    })
    if len(roots) != 1:
        die(f"Ожидался один .app, найдено: {roots}")
    return roots[0]

def file_info(name: str, src: Path) -> zipfile.ZipInfo:
    st = src.stat()
    zi = zipfile.ZipInfo(norm(name))
    zi.date_time = tuple(time.localtime(st.st_mtime)[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 3
    zi.external_attr = 0o100644 << 16
    return zi

def bytes_info(name: str) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(norm(name))
    zi.date_time = tuple(time.localtime()[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 3
    zi.external_attr = 0o100644 << 16
    return zi

def collect_webdist(root: Path) -> list[tuple[Path, str]]:
    files = []
    for src in sorted(root.rglob("*")):
        if src.is_file():
            files.append((src, src.relative_to(root).as_posix()))
    if not any(rel == "index.html" for _, rel in files):
        die(f"В {root} не найден index.html. Сначала пересобери WebDist.")
    if not any(rel == "launcher.html" for _, rel in files):
        die(f"В {root} не найден launcher.html.")
    return files

def collect_mod(root: Path) -> tuple[list[Path], list[Path]]:
    chosen: list[Path] = []
    skipped: list[Path] = []
    seen: dict[str, Path] = {}
    for src in sorted(root.rglob("*")):
        if not src.is_file():
            continue
        if src.name.lower() == "modcd.ini":
            continue
        if src.suffix.lower() not in SUPPORTED_MOD_EXT:
            skipped.append(src)
            continue
        key = src.name.lower()
        if key in seen:
            die(
                "Дубликаты имени файла после упаковки мода:\n"
                f"  {seen[key]}\n"
                f"  {src}"
            )
        seen[key] = src
        chosen.append(src)
    return chosen, skipped

def generated_meta(mod_id: str, name: str) -> bytes:
    return (
        "[General]\n"
        f"ID={mod_id}\n"
        f"Name={name}\n"
        f"Description={name} packaged for the iPad launcher.\n"
        "Version=unknown\n"
    ).encode("utf-8")

def parse_mod_arg(raw: str, cwd: Path) -> tuple[str | None, Path]:
    # Preferred form: id=path. Bare paths remain supported.
    if "=" in raw:
        maybe_id, maybe_path = raw.split("=", 1)
        if re.fullmatch(r"[A-Za-z0-9_-]+", maybe_id.strip()):
            return maybe_id.strip().lower(), (cwd / maybe_path).resolve()
    return None, (cwd / raw).resolve()

def make_mod_spec(raw: str, cwd: Path) -> ModSpec:
    explicit_id, root = parse_mod_arg(raw, cwd)
    if not root.is_dir():
        die(f"Не найдена папка мода: {root}")

    original_meta = root / "modcd.ini"
    meta = original_meta.read_bytes() if original_meta.is_file() else b""
    parsed = parse_general_ini(meta) if meta else {}

    mod_id = explicit_id or parsed.get("id")
    if not mod_id:
        if root.name.lower() in {"scorchedearth", "scorched-earth"}:
            mod_id = "scorched-earth"
        else:
            mod_id = slugify(root.name)
    mod_id = slugify(mod_id)

    if not meta:
        name = root.name.replace("-", " ").replace("_", " ").strip().title()
        meta = generated_meta(mod_id, name)
    elif parsed.get("id", "").strip().lower() != mod_id:
        # The folder ID is authoritative for our packaged layout. Rewrite/add ID
        # while preserving the rest of the original metadata.
        try:
            text = meta.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = meta.decode("cp1252", errors="replace")
        if re.search(r"(?im)^\s*ID\s*=", text):
            text = re.sub(r"(?im)^\s*ID\s*=.*$", f"ID={mod_id}", text, count=1)
        else:
            text = re.sub(r"(?im)^\s*\[General\]\s*$", f"[General]\nID={mod_id}", text, count=1)
        meta = text.encode("utf-8")

    files, skipped = collect_mod(root)
    if not files:
        die(f"Не найдено поддерживаемых файлов мода в {root}")
    return ModSpec(mod_id, root, files, skipped, meta)

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build one RA2 iPad app containing RA2, Yuri's Revenge and multiple RA2 mods."
    )
    ap.add_argument("--shell", default="input/RA2-shell-unsigned.ipa")
    ap.add_argument("--base-full", default="input/RA2-YR-FULL-unsigned.ipa")
    ap.add_argument("--webdist", default="redalert2/dist")
    ap.add_argument(
        "--mod",
        action="append",
        default=[],
        help="Repeatable. Use id=PATH (recommended) or just PATH."
    )
    ap.add_argument("--output", default="output/RA2-ALL-IN-ONE-FULL-unsigned.ipa")
    ap.add_argument("--bundle-id", default="com.dvorov.ra2yr")
    ap.add_argument("--name", default="Red Alert 2")
    a = ap.parse_args()

    cwd = Path.cwd()
    shell = (cwd / a.shell).resolve()
    base = (cwd / a.base_full).resolve()
    webdist = (cwd / a.webdist).resolve()
    output = (cwd / a.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if not shell.is_file():
        die(f"Не найден новый shell IPA: {shell}")
    if not base.is_file():
        die(f"Не найден рабочий RA2/YR FULL IPA: {base}")
    if not webdist.is_dir():
        die(f"Не найден свежий WebDist: {webdist}")

    if a.mod:
        mod_args = a.mod
    else:
        mods_root = cwd / "mods"
        if not mods_root.is_dir():
            die(f"Не найдена папка модов: {mods_root}")
        all_mod_dirs = sorted(p for p in mods_root.iterdir() if p.is_dir())
        mod_dirs = [p for p in all_mod_dirs if (p / "modcd.ini").is_file()]
        skipped_dirs = [p for p in all_mod_dirs if not (p / "modcd.ini").is_file()]
        if skipped_dirs:
            print("Рабочие/неподготовленные папки пропущены (нет modcd.ini):")
            for p in skipped_dirs:
                print(f"  {p.name}")
        if not mod_dirs:
            die(f"В {mods_root} нет подготовленных модов с modcd.ini.")
        mod_args = [f"{slugify(p.name)}={p}" for p in mod_dirs]
    mods = [make_mod_spec(raw, cwd) for raw in mod_args]
    ids = [m.mod_id for m in mods]
    if len(ids) != len(set(ids)):
        die(f"Повторяющиеся ID модов: {ids}")

    web_files = collect_webdist(webdist)

    print("=== RA2 ALL-IN-ONE iPad ===")
    print("  Red Alert 2")
    print("  Yuri's Revenge")
    for mod in mods:
        meta = parse_general_ini(mod.meta)
        print(f"  {meta.get('name', mod.mod_id)} [{mod.mod_id}]")
    print(f"WebDist: {len(web_files)} файлов")
    for mod in mods:
        print(f"{mod.mod_id}: {len(mod.files)} файлов, пропущено: {len(mod.skipped)}")

    with zipfile.ZipFile(shell, "r") as zs, zipfile.ZipFile(base, "r") as zb:
        shell_names = zs.namelist()
        base_names = zb.namelist()
        shell_app = find_app_root(shell_names)
        base_app = find_app_root(base_names)

        shell_web = shell_app + "WebDist/"
        shell_game = shell_app + "GameRes/"
        shell_info = shell_app + "Info.plist"
        base_game = base_app + "GameRes/"
        base_manifest = base_game + "manifest.json"

        if shell_info not in shell_names:
            die("В shell IPA нет Info.plist")
        if base_manifest not in base_names:
            die("В RA2/YR FULL IPA нет GameRes/manifest.json")

        plist = plistlib.loads(zs.read(shell_info))
        plist["CFBundleIdentifier"] = a.bundle_id
        plist["CFBundleDisplayName"] = a.name
        plist["CFBundleName"] = a.name
        new_plist = plistlib.dumps(plist, fmt=plistlib.FMT_BINARY)

        old_manifest = json.loads(zb.read(base_manifest))
        selected_prefixes = tuple(f"mods/{m.mod_id}/" for m in mods)
        manifest_files = [
            f for f in old_manifest.get("files", [])
            if not str(f.get("path", "")).lower().startswith(selected_prefixes)
        ]

        for mod in mods:
            manifest_files.append({
                "path": f"mods/{mod.mod_id}/modcd.ini",
                "size": len(mod.meta),
            })
            for src in mod.files:
                manifest_files.append({
                    "path": f"mods/{mod.mod_id}/{src.name}",
                    "size": src.stat().st_size,
                })

        manifest_files.sort(key=lambda x: str(x["path"]).lower())
        manifest_bytes = json.dumps(
            {"files": manifest_files}, indent=1, ensure_ascii=False
        ).encode("utf-8")

        if output.exists():
            output.unlink()

        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED,
            compresslevel=6, allowZip64=True
        ) as zo:
            for item in zs.infolist():
                n = norm(item.filename)
                if n == shell_info:
                    clone = zipfile.ZipInfo(n)
                    clone.date_time = item.date_time
                    clone.compress_type = item.compress_type
                    clone.comment = item.comment
                    clone.extra = item.extra
                    clone.internal_attr = item.internal_attr
                    clone.external_attr = item.external_attr
                    clone.create_system = item.create_system
                    clone.flag_bits = item.flag_bits
                    zo.writestr(clone, new_plist)
                    continue
                if n.startswith(shell_web) or n.startswith(shell_game):
                    continue
                zo.writestr(item, zs.read(item.filename))

            web_total = 0
            for src, rel in web_files:
                data = src.read_bytes()
                zo.writestr(file_info(shell_web + rel, src), data)
                web_total += len(data)

            game_total = 0
            for item in zb.infolist():
                n = norm(item.filename)
                if not n.startswith(base_game):
                    continue
                rel = n[len(base_game):]
                if not rel or rel == "manifest.json":
                    continue
                rel_lower = rel.lower()
                if any(rel_lower.startswith(f"mods/{m.mod_id}/") for m in mods):
                    continue
                new_name = shell_game + rel
                data = zb.read(item.filename)
                clone = zipfile.ZipInfo(new_name)
                clone.date_time = item.date_time
                clone.compress_type = item.compress_type
                clone.comment = item.comment
                clone.extra = item.extra
                clone.internal_attr = item.internal_attr
                clone.external_attr = item.external_attr
                clone.create_system = item.create_system
                clone.flag_bits = item.flag_bits
                zo.writestr(clone, data)
                game_total += len(data)

            mod_totals: dict[str, int] = {}
            for mod in mods:
                zo.writestr(
                    bytes_info(shell_game + f"mods/{mod.mod_id}/modcd.ini"),
                    mod.meta
                )
                total = 0
                for src in mod.files:
                    data = src.read_bytes()
                    zo.writestr(
                        file_info(shell_game + f"mods/{mod.mod_id}/{src.name}", src),
                        data
                    )
                    total += len(data)
                mod_totals[mod.mod_id] = total

            zo.writestr(bytes_info(shell_game + "manifest.json"), manifest_bytes)

    print("\nГОТОВО:")
    print(output)
    print(f"Bundle ID: {a.bundle_id}")
    print(f"WebDist: {web_total / 1024 / 1024:.1f} MB")
    print(f"Base RA2/YR GameRes: {game_total / 1024 / 1024:.1f} MB")
    for mod in mods:
        print(f"{mod.mod_id}: {mod_totals[mod.mod_id] / 1024 / 1024:.1f} MB")
    print(f"IPA: {output.stat().st_size / 1024 / 1024:.1f} MB")

if __name__ == "__main__":
    main()
