# Local All-in-One layout

Keep all local game resources under this repository folder:

```
mods/
  scorched-earth/
  eagle-red/
  moomans-rules/

input/
  RA2-shell-unsigned.ipa
  RA2-YR-FULL-unsigned.ipa

output/
  RA2-ALL-IN-ONE-FULL-unsigned.ipa
```

The contents of `mods/`, `input/`, and `output/` are local build assets and are ignored by Git.

Run:

```powershell
.\build-all.ps1
```

The packager automatically discovers every direct subfolder of `mods/` and adds it to the IPA manifest. The launcher discovers packaged mods at runtime through each mod's `modcd.ini`.
