# Source provenance

Rocket-R base (host, launcher, controls, build/platform family):
https://github.com/ThatGuyMcd/Rocket-R/tree/133070e264350f17257a520ae0de4da98ce445b0

Glover initial USA layout/decompilation reference:
https://github.com/Rainchus/Glover/tree/f2d2b2824e29a5d9b00718a283a3cb243be3ca52

N64Recomp:
https://github.com/N64Recomp/N64Recomp/tree/81213c1831fab2521a6a5459c67b63437d67e253

N64ModernRuntime:
https://github.com/N64Recomp/N64ModernRuntime/tree/ae1ffbb909d9f93c88c41830deb539f7feef5ed2

RT64:
https://github.com/rt64/rt64/tree/6f1c2d99a4ea571c139f449c326fd176ba8f3496

SDL2:
https://github.com/libsdl-org/SDL/tree/adf31f6ec0be0f9ba562889398f71172c7941023

n64sym (signature/relocation identification; MIT):
https://github.com/shygoo/n64sym/tree/ccf4600f3389f1a84bde23339225cf372fdf7712

Save-type evidence, checked 2026-09-30 against the canonical ROM MD5:
https://github.com/mupen64plus/mupen64plus-core/blob/master/data/mupen64plus.ini

No ROM, extracted copyrighted assets, compiler SDK binaries, font files or
third-party dependency archives are included in this source ZIP. The first
native build fetches the pinned source dependencies. Original upstream notices
are retained; game ownership is not transferred by this integration.

## Boot.5 input-boundary sources

The real n64sym report is preserved in tests/data/glover-sdk-symbols-20260930.txt.
Its archive/member hashes and the exact upstream symbol-set reference are in
tests/data/sdk-replay-provenance.json. The runtime-name JSON is an extracted
test fixture, not a claimed copy of the complete upstream dependency.

The ROM-origin normalisation and symbol classification are based on N64Recomp
81213c1831fab2521a6a5459c67b63437d67e253, src/elf.cpp. Instruction/hook lookup is
in src/main.cpp. The high-VRAM entrypoint patch retained from Rocket-R is
patches/n64recomp/0001-fix-high-vram-entrypoint-comparison.patch at base commit
133070e264350f17257a520ae0de4da98ce445b0.

The new modules are independent input tooling, not post-processing of generated
C. The SHA-256 in config/sdk-aliases.json describes the two user-ROM getter
bodies; those original instruction bytes are not included as a game asset.
