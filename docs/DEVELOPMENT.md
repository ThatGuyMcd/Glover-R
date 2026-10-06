# Developing Glover-R

Make changes in the main source checkout. The `native/` templates and checked
adapters in `scripts/glover/` assemble a separately owned tree at
`build/native-src`, using the pinned Rocket-R source.

Host code lives in `native/src`. Startup uses `game_registration.*` and
`glover_boot_probe.cpp`, with Glover's own entry point, stack, BSS range, save
ID and audio inputs. ROM-checked guest hooks live in
`runtime-recomp/glover.us.recomp-policy.json`.

Don't edit dependency checkouts or `RecompiledFuncs`, `RecompiledPatches` and
generated RSP output. Dependency changes belong in checked patches. The normal
pipeline regenerates CPU/RSP output, hashes it and checks it after compilation.

Source preparation checks upstream inputs, patch hashes and transformation
anchors. The ownership inventory checks existing native source before
reassembly. Investigate failed guards instead of removing them or inserting
empty game functions to force the build to succeed.

## Checking a change

```sh
python -B -m unittest discover -s tests
python -B scripts/self_check.py --write-manifest
python -B scripts/self_check.py
```

Run `ONE-CLICK-BUILD.cmd` for a game build, then test its executable. Always
produce Windows and Linux AppImage packages together. `Build-Linux.sh` packages
the shared sources after the Windows workflow has prepared and generated them.
Unit tests and source assembly alone do not count as a game boot.

## Build helpers

| Helper | Purpose |
| --- | --- |
| `PREPARE-NATIVE-SOURCE.cmd` | Fetch and assemble the pinned native source without compiling the game. |
| `DIAGNOSE-GLOVER.cmd` | Run source, regression-test, ROM identity and startup checks without compiling the game. |
| `TEST-GLOVER.cmd` | Start the local Windows build. |
| `COLLECT-GLOVER-DIAGNOSTICS.cmd` | Collect text diagnostics for a failed build or session. |

The game CMake template is `native/CMakeLists.txt`. The builder runs
`scripts/preflight.py` before fetching and assembling native source.
The regression fixtures under `tests/` are required by preflight and are kept
in source; local reports, verification history, captures and generated output
are excluded from Git and public source packages.

Keep ROMs, saves, settings, ELF files and signing keys private. Preserve them
when cleaning build output, especially Android signing keys under the private
native build folder. Don't commit dependency checkouts or release binaries.
