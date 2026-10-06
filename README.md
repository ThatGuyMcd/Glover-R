# GLOVER-R

<img width="900" alt="Glover-R logo" src="native/src/UI/Glover-R-green-full-resolution.png" />

Glover Recompiled

Glover-R brings Glover to Windows and Linux, with widescreen, smoother frame
rates and a modern camera. You can set the graphics and controls up how you
like, all from the launcher or while you're playing!

Recompilation project by **ThatGuyMcd**.

## Getting started

The current release is **1.0.0**. Download the package for your device from the
GitHub Releases section, then follow the steps below.

| Device | Package | How to start |
| --- | --- | --- |
| Windows x64 | `Glover-R-1.0.0-Windows-x64.zip` | Extract the ZIP and open `Glover-R.exe`. Keep its DLLs and assets alongside it. |
| Linux x64 | `Glover-R-1.0.0-Linux-x86_64.AppImage` | Make the AppImage executable, then open it. |
| Linux portable | `Glover-R-1.0.0-Linux-x86_64-Portable.tar.gz` | Extract it and run `Launch-Glover-R.sh`. |
| Steam Deck | `Glover-R-1.0.0-Linux-x86_64-SteamDeck.tar.gz` | Extract it and run `START-GLOVER-R.sh`. |

The **Release Bundle** includes all of these, the Mod SDK and Modern Camera.
Use the **x86_64** package on Steam Deck.

You'll need your own unmodified **USA ROM**. Choose it in the launcher, then
select **Play**. The game and its original assets aren't included.

Supported ROM: USA, revision 0, game code `NGVE`, 8 MiB. The launcher accepts
`.z64`, `.n64` and `.v64` byte orders. The canonical SHA-1 is
`270be17b3c8da9b88a7b99c2a545b0bce16837f4`.

## Graphics and controls

Press **F1** or **Escape** to open settings while playing. **F11** or
**Alt+Enter** switches fullscreen. You can remap F1 and F11 in
**Controls > Shortcuts**.

Graphics options include widescreen, resolution, frame rate, interpolation,
texture filtering, FOV and draw distance. The game keeps its original speed
when you use a higher frame rate. **Original** restores the original graphics
settings. See the [graphics guide](docs/GRAPHICS.md) for the full list and which
changes need a restart.

The launcher and in-game settings use the same red and coin-gold design. The
overlay panels are 75% opaque, so you can still see the game underneath.

**Controls > Bindings** opens Controller Studio. Choose an N64 control and
assign a keyboard, mouse or controller input. **Guided Setup** takes you through
the controls, and **Test Inputs** lets you check everything is working.

## Mods and Modern Camera

The **Mods** tab lets you add mods and texture packs, choose a profile and
change each mod's settings. Use **Browse / Add Mods** to install a package.
Modded profiles have their own saves; **Original Game** starts without mods.

**Modern Analogue Camera 1.0.2** adds right-stick, keyboard and mouse look in
third-person and first-person. You can change its speed, response, momentum
and axis inversion while playing. It still follows Glover, keeps the angle you
choose, and retains the original camera modes.

Open **Controls > Camera** to see or remap the camera controls:

- **I / J / K / L** or the right stick: look around.
- **O** or left-stick click: cycle the three original zoom stages.
- **P** or the top face button: enter or leave first-person while stationary.

The [modding guide](docs/MODDING.md) covers installation and making your own
mods, including the SDK services that still need Glover-specific integration.

## Testing and reporting problems

Windows has been tested through the intro, menus and gameplay, including the
Modern Camera controls. Windows and Linux builds pass the automated checks.
I still need gameplay testing on Linux and Steam Deck hardware, and longer
play sessions on all platforms.

If something goes wrong, please report it in GitHub Issues. Include your
platform, what happened, the steps to reproduce it, and whether you had mods
enabled. **Graphics > Diagnostics** has the live log.
`COLLECT-GLOVER-DIAGNOSTICS.cmd` can collect the Windows logs into a ZIP.
Please check logs before sharing them and keep ROMs and saves out of reports.

## Building from source

Run `ONE-CLICK-BUILD.cmd` from the main project folder. It prepares the pinned
source and dependencies, asks for your ROM, and builds the selected packages.
Windows builds also include a Linux x64 AppImage. Packages go into `dist/`.

Please make changes through the patch pipeline. Don't edit the generated
`RecompiledFuncs`, `RecompiledPatches` or dependency checkouts.

See the [development guide](docs/DEVELOPMENT.md) and
[native build notes](docs/NATIVE-README.md) for the details.

## Credits and licences

Glover-R is based on [Rocket-R](https://github.com/ThatGuyMcd/Rocket-R).
It uses Glover layout research from [Rainchus](https://github.com/Rainchus/Glover),
N64Recomp, RSPRecomp, N64ModernRuntime, RT64, SDL2 and n64sym.
Thanks to everyone whose work made this possible!

The launcher uses the independently licensed Bungee and Selawik fonts. Their
licence notices are included with the source and release packages.
See [the project licence](LICENSE.md), [GPL licence text](LICENSE) and
[component provenance](docs/PROVENANCE.md).

Glover and its original game data belong to their respective rights holders.
