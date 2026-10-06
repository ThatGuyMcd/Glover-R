# Glover-R — 1.0.1

Glover-R lets you play Glover on Windows and Linux with widescreen, smoother
frame rates and a modern camera. The launcher and F1 settings use the same
red and coin-gold design, with 75% opaque in-game panels.

Recompilation project by **ThatGuyMcd**.

## What's changed in 1.0.1

The first launch should now be much quicker! Glover no longer compiles the
unused Rocket skybox filter. Graphics preparation has a progress display,
and the game starts once its shaders are ready.

I've also removed an old graphics diagnostic that could crash the game when
using the original frame rate.

## Getting started

On Windows, extract the ZIP and open `Glover-R.exe`. Keep its DLLs and assets
alongside it. On Linux, make the AppImage executable and open it, or extract
the Portable package and run `Launch-Glover-R.sh`. For Steam Deck, use the
x86_64 package and run `START-GLOVER-R.sh`.

Choose your own unmodified USA ROM in the launcher, then select **Play**.
The game and its original assets aren't included.

The supported ROM is USA revision 0, game code `NGVE`, 8 MiB. `.z64`, `.n64`
and `.v64` byte orders are accepted. The canonical SHA-1 is
`270be17b3c8da9b88a7b99c2a545b0bce16837f4`.

## Settings and controls

**F1** or **Escape** opens settings while playing. **F11** or **Alt+Enter**
switches fullscreen. **Controls > Bindings** opens Controller Studio, with
Guided Setup and Test Inputs to help you set everything up.

Graphics options include widescreen, resolution, higher frame rates,
interpolation, filtering, FOV and draw distance. Higher frame rates keep the
game running at its original speed. Skybox texture filtering isn't included.
See the [graphics guide](GRAPHICS.md) for settings and restart requirements.

The launcher uses Bungee and Selawik fonts. Both fonts and their licence
notices are included with the package.

## Mods and Modern Camera

Use **Mods > Browse / Add Mods** to install mods or texture packs. Choose a
profile and enable the mods you want. Modded profiles have separate saves;
**Original Game** starts without mods.

Modern Camera 1.0.2 supports right-stick, I/J/K/L and mouse look in both views.
It follows Glover and keeps your chosen angle. **O / left-stick click** cycles
the three original zoom stages. **P / top face button** enters or leaves
first-person while stationary. **Controls > Camera** lets you remap these.

See the [modding guide](MODDING.md) for installation and the standalone
SDK, including the native SDK adapters that are still being worked on.

## Building from source

Run `ONE-CLICK-BUILD.cmd` from the main Glover-R source folder. It downloads
the pinned source and dependencies, prepares `build/native-src`, checks the
ROM and generates the CPU/RSP code before building the packages.
Windows builds also produce a Linux x64 AppImage. Finished packages go into
the main project's `dist/` folder.

The copied build helper inside `build/native-src` needs inputs from the main
builder, so please start from the main project folder. Make changes in the
maintained source and patch pipeline. Don't edit `RecompiledFuncs`,
`RecompiledPatches`, the generated workspace or dependency checkouts.

The native runtime starts from Rocket-R commit
`133070e264350f17257a520ae0de4da98ce445b0`. Glover has its own ROM registration,
startup, audio inputs and save ID. Internal `rocket` names are kept where the
runtime needs them; Glover doesn't use the Rocket ROM or saves.

## Logs and testing

Windows gameplay, menus and Modern Camera controls have been tested.
Windows and Linux builds pass ten native test suites each, plus 314 Python
checks for the 1.0.1 release (one optional check was skipped). Longer sessions, full-game completion and Linux
hardware gameplay still need testing.

**Graphics > Diagnostics** shows the live log. Build logs are collected in
`dist/` after a run. `COLLECT-GLOVER-DIAGNOSTICS.cmd` also collects text session
logs on Windows. Please check logs before sharing them.

Windows settings and saves are under `%APPDATA%\Glover-R`. Linux uses
`$XDG_CONFIG_HOME/glover-r` or `~/.config/glover-r`.
