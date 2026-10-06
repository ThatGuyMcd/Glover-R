# Glover-R mods — development integration

The mod library and desktop workflow use Rocket-R's current implementation with Glover's game identity and red/gold presentation. The test package is a separately compiled MIPS `.nrm`, loaded through the same importer as other mods. Original Game remains an empty profile using the original save folder.

## Install and play

Open **Mods → Browse → Install Camera Mod**. Installation creates **My Mods** if Original Game is selected. Use **Installed → Details and settings** for camera options and input remaps. The profile selector and **Manage Profiles** dialog match Rocket-R's workflow. Add Mods accepts `.nrm`, `.rtz`, ZIP collections and exported JSON profiles; desktop drag-and-drop and `--install-mod <path>` use the same validation.

Use a different profile for a different mod setup. Exports contain hashes, version selections, settings and input bindings; they contain neither packages nor saves. The launcher distinguishes the selected setup for the next launch from the packages already running. Dependency, version, conflict and exclusive-resource errors block launch with an explanation.

After an unclean modded session, the next launch falls back to Original Game. **Try My Mods Again** retains the selected profile and retries it. `--without-mods` also selects the safe original session. Modded saves live in a separate profile folder. Installing a package never edits the private original ROM.

## Camera test package

`glover_modern_camera.nrm` uses Rocket's guest camera algorithm and settings: speed, deadzone, response, momentum and horizontal/vertical inversion. Default look inputs are right stick and I/J/K/L. The settings panel supplies mouse look, sensitivity, recenter binding and camera-action remapping. The exact included package can remain in standby and switch live; arbitrary packages do not inherit that privilege.

Open **Controls → Camera** in the launcher or F1 overlay to see and remap camera inputs. The same settings remain available in the mod's Details and settings panel. **Cycle zoom (3 stages)** defaults to **O / left-stick click** and sends Glover's original C-Down input. **First-person view** defaults to **P / top face button** and sends original C-Up. Tap and release to cycle zoom or switch view; enter first-person while stationary. Right stick, I/J/K/L and mouse look work in both views. The shared Invert Y setting reverses vertical look in both views. First-person also retains original movement-stick or W/A/S/D look. Press the view button again to return to third-person orbiting. If your controller has no stick-click buttons, assign Cycle zoom to an available button here.

The Windows diagnostic trace verified the native zoom index cycling through all three values and the native first-person state entering and leaving with the mod enabled. These are Glover's original mode handlers; the mod does not substitute a separate zoom or first-person camera.

The Glover bridge maps eye/target vectors and requests into the native camera-update path. Only normal authored camera updates should own input; loading warm-up, file select and unsupported views retain native control. Recenter is mapped from Glover's native follow heading. First-person dispatches the guest look event after original stick input and before the original pitch-limit and geometry checks. It updates native yaw/pitch targets, preserving Glover's eye movement and view publication. Collision behavior and transitions require gameplay validation; a separate native follow-spring adjustment remains pending. Loading the package successfully does not establish camera feel or collision behavior.

## Build a mod

From the project after a native build:

```text
python scripts/glover_sdk.py init my_mod --id my_mod
python scripts/glover_sdk.py build my_mod --wsl --output build/mods
python scripts/glover_sdk.py validate build/mods/my_mod.nrm
```

On Windows the guest compiler runs in Ubuntu-24.04 WSL with Clang and LLD. Linux uses its native Clang and LLD. `--tool`, `--symbols` and `--data-symbols` select the matching RecompModTool and symbol dumps. SDK archives carry headers, tools and symbols, without a game ROM. The same guest package format works with the Windows and Linux host builds.

The `rocket/` include namespace, `rocket.json` metadata filename and `rocket_*` import/event names remain stable ABI conventions. They do not make a Rocket game package compatible: Glover manifests require `game_id = "glover"` and minimum host version `0.4.0`. Never reuse Rocket native addresses or object layouts in a Glover mod.

SDK 1 provides camera callbacks. SDK 2 provides managed activation, callbacks, settings commands, action remapping, scoped resources/saves, events, system ownership, HUD and custom PCM audio. Raw restart hooks/replacements use the supplied matching function/data symbols and verified signatures. Functions implementing port fixes are protected by an inventory generated from the checked recomp policy.

**Current SDK 2 native binding gaps:** native object services, original sound/music controls, custom mesh/actor presentation and native-render replacement are not advertised. Packages requiring them are rejected. Their Rocket adapters cannot be used on Glover, and full development-SDK parity is still work in progress. Portable world/collision code is present; native scene integration is not complete. These services still need Glover-specific integration and testing.

## Assets and package rules

Packages are immutable and identified by SHA-256. ZIP paths, resource names, expanded size, duplicate/case-colliding names, malformed code pairs and native libraries are validated before launch. A hash identifies bytes; it is not an author signature or a sandbox for guest code.

SDK asset patches target the canonical 8 MiB USA Glover cartridge. The header and initial game code/data/rodata region through ROM offset `0xF6680` are protected. Separate compatible authored asset layers can be composed privately; overlaps are rejected. No extracted game assets or patched ROM belong in a release.

Use maintained host sources and checked patch-policy hooks for changes to Glover-R itself. Do not manually edit generated recomp functions, generated patches or dependency/submodule source.
