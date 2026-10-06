# Glover's patch pipeline

This is where I keep the ROM-checked Glover hook policy. Changes to the game
should go through this pipeline.

`glover.us.recomp-policy.json` describes the hooks and instruction patches.
Each site is checked against the original ROM instructions, including its
delay slot and ROM/VRAM address, before the recompiler configuration is written.
The policy covers the startup, audio, graphics, timing and camera fixes used
by the current build.

`scripts/glover/native_inputs.py` combines the policy with the original-byte
ELF and checked audio metadata. The builder then generates CPU and RSP code
inside `build/native-src`. It hashes that output and checks it again after
compilation.

Please don't edit `RecompiledFuncs`, `RecompiledPatches` or dependency
checkouts. Update the maintained source or verified policy and let the normal
pipeline regenerate the output.

The 1.0.0 build has been tested in Windows gameplay. That doesn't make every
function boundary or indirect target correct. If a new hook fails its original
instruction check, investigate the mismatch rather than removing the check.
See the [development guide](../docs/DEVELOPMENT.md) for the build rules.
