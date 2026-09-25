#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import plistlib
import sys
import time
import zipfile
from pathlib import Path

MOD_ID = "scorched-earth"
SUPPORTED_MOD_EXT = {
    ".mix", ".mmx", ".ini", ".csf", ".mpr", ".map", ".pkt", ".png", ".webm",
    ".bag", ".idx",
}

def die(msg: str) -> None:
    print(f"\nОШИБКА: {msg}", file=sys.stderr)
    raise SystemExit(1)

def norm(s: str) -> str:
    return s.replace("\\", "/")

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

def mod_meta() -> bytes:
    return b"""[General]
ID=scorched-earth
Name=Scorched Earth
Description=Scorched Earth RA2 overhaul for the iPad launcher.
Author=ATHSE
Version=2023-07-20
Website=https://www.moddb.com/mods/scorched-earth-ra2-mod-with-smart-ai
"""

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build one RA2 iPad app containing RA2, Yuri's Revenge and Scorched Earth."
    )
    ap.add_argument("--shell", default="RA2-shell-unsigned.ipa")
    ap.add_argument("--base-full", default="RA2-YR-FULL-unsigned.ipa")
    ap.add_argument("--webdist", default="WebDist")
    ap.add_argument("--mod", default="ScorchedEarth")
    ap.add_argument("--output", default="RA2-ALL-IN-ONE-FULL-unsigned.ipa")
    ap.add_argument("--bundle-id", default="com.dvorov.ra2yr")
    ap.add_argument("--name", default="Red Alert 2")
    a = ap.parse_args()

    cwd = Path.cwd()
    shell = (cwd / a.shell).resolve()
    base = (cwd / a.base_full).resolve()
    webdist = (cwd / a.webdist).resolve()
    mod = (cwd / a.mod).resolve()
    output = (cwd / a.output).resolve()

    if not shell.is_file():
        die(f"Не найден новый shell IPA: {shell}")
    if not base.is_file():
        die(f"Не найден рабочий RA2/YR FULL IPA: {base}")
    if not webdist.is_dir():
        die(f"Не найден свежий WebDist: {webdist}")
    if not mod.is_dir():
        die(f"Не найдена папка Scorched Earth: {mod}")

    web_files = collect_webdist(webdist)
    mod_files, skipped = collect_mod(mod)
    if not mod_files:
        die("Не найдено файлов Scorched Earth для упаковки.")

    print("=== RA2 ALL-IN-ONE iPad ===")
    print("  Red Alert 2")
    print("  Yuri's Revenge")
    print("  Scorched Earth")
    print(f"WebDist: {len(web_files)} файлов")
    print(f"Scorched Earth: {len(mod_files)} файлов")
    print(f"Пропущено служебных файлов мода: {len(skipped)}")

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
        manifest_files = [
            f for f in old_manifest.get("files", [])
            if not str(f.get("path", "")).lower().startswith(f"mods/{MOD_ID}/")
        ]

        original_meta = mod / "modcd.ini"
        meta = original_meta.read_bytes() if original_meta.is_file() else mod_meta()
        manifest_files.append({"path": f"mods/{MOD_ID}/modcd.ini", "size": len(meta)})
        for src in mod_files:
            manifest_files.append({
                "path": f"mods/{MOD_ID}/{src.name}",
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
                if rel.lower().startswith(f"mods/{MOD_ID}/"):
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

            zo.writestr(bytes_info(shell_game + f"mods/{MOD_ID}/modcd.ini"), meta)
            mod_total = 0
            for src in mod_files:
                data = src.read_bytes()
                zo.writestr(file_info(shell_game + f"mods/{MOD_ID}/{src.name}", src), data)
                mod_total += len(data)

            zo.writestr(bytes_info(shell_game + "manifest.json"), manifest_bytes)

    print("\nГОТОВО:")
    print(output)
    print(f"Bundle ID: {a.bundle_id}")
    print(f"WebDist: {web_total / 1024 / 1024:.1f} MB")
    print(f"Base RA2/YR GameRes: {game_total / 1024 / 1024:.1f} MB")
    print(f"Scorched Earth: {mod_total / 1024 / 1024:.1f} MB")
    print(f"IPA: {output.stat().st_size / 1024 / 1024:.1f} MB")

if __name__ == "__main__":
    main()
