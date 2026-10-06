# Graphics controls

Glover-R Graphics.7 uses the same graphics options as Rocket-R 1.0.1, except
for the skybox filtering/dithering reduction control. Old saved skybox values
are ignored and the renderer keeps that effect at zero.

Open **Graphics** in the launcher or in the pause/settings overlay. **Reset
Graphics** returns to the working Original preset. Your choices persist in
Glover-R's own configuration directory.

| Tab | Controls |
| --- | --- |
| Display | Renderer API; windowed/fullscreen; VSync; original, fit-window, 16:9, 16:10, 21:9 or custom aspect; render resolution; 1Ã¢â‚¬â€œ4x downsampling; Original, Match display or custom 30Ã¢â‚¬â€œ500 FPS; double/triple buffering; framebuffer precision; hardware resolve |
| Image | None/2x/4x/8x MSAA; nearest/linear/anti-aliased pixel scaling; 1Ã¢â‚¬â€œ16x anisotropy; distant texture detail; replacement texture mip bias; Off/Scanlines/CRT/custom shader; effect strength |
| Camera & Distance | FOV offset Ã¢Ë†â€™20 to +40 degrees; draw distance 1Ã¢â‚¬â€œ6x |
| Diagnostics | Live log; performance overlay; interpolation overlay; detailed presentation statistics |

Original, Modern, High quality and Performance presets match Rocket-R's choices.
Changing an individual option switches the preset to Custom.

Renderer API is selected before launching. Buffering, framebuffer precision,
anisotropy and custom shader changes require restarting the game. Other settings
apply during play. Custom shader files go in the configuration's `shaders`
folder: `.dxil` for Direct3D 12 and `.spv` for Vulkan. API choices are shown only
on supported platforms.

Widescreen expands perspective geometry once in RT64. Full-screen menu backgrounds
and transition images scale uniformly to cover the viewport, with equal cropping
above and below on wider displays. Their texture strips share one canvas transform
to keep the image continuous. Smaller menu and HUD images keep their authored
proportions. High refresh interpolates presentation without speeding
up the simulation. Glover completes a frame over multiple graphics tasks, so
RT64 groups those passes before matching and selects their source cadence from
retail retraces. Gameplay is normally 20 Hz; some intro and menu passes use 30 Hz. Uncertain frame matches may stay at the original animation cadence.

FOV changes the verified gameplay perspective-call argument. File select, the
secondary screen camera and the final transition-overlay pass keep their authored
FOV and distance. Draw distance extends gameplay projection far planes and two
render visibility checks, capped at the
signed guest distance range. Temporary stack arguments are restored after the
projection call. Camera globals, scene activation, AI and particle lifetimes
remain authored. Authored fog and scene visibility can still limit what appears
at longer distances.

Changes are maintained in the outer patch pipeline. Dependency checkouts and
generated game sources are never edited manually. The working Boot.12 packages
remain available as a fallback in `dist`.

## Widescreen validation

The user confirmed widescreen works after the full-screen clear correction on
2026-10-01. Smooth interpolation and correct HUD proportions were also confirmed
in the preceding tests. The final test reached gameplay and closed normally.

Glover's fill commands end at inclusive quarter-pixel coordinates 1279 by 959,
while its full-screen scissor ends at 1280 by 960. RT64 already expanded the 3D
viewport, but interpreted those fills as local 4:3 rectangles. Graphics.2
normalises only complete native-frame fills before their aspect conversion,
following the full-screen clear correction used in DKR-R. Local menu rectangles
and the global rectangle tolerance setting retain their existing behavior.

Dependency changes are maintained as checked patches under `native/patches`.
Generated game code is unchanged. Complete split-task frame history also retains
separate world/HUD mappings and guest vertex branch state across task boundaries.

Graphics.3 checks the actual two-command FullSync/EndDL frame terminator.
Empty setup tasks inside the intro do not close a frame. Presentation deadlines
retain their target cadence across short swap-chain waits and rebase after long
pauses. The user confirmed a stable intro and gameplay FPS within 1 to 2 of the target.

Graphics.4 adds aspect-preserving cover scaling for complete screen images before
their texture strips are drawn. Short scrolling sky sprites keep the existing
widescreen treatment. The native contracts check uniform scaling, centered crop,
strip alignment, the unchanged 4:3 result, and cropping on narrow viewports.
The user confirmed improved backgrounds. Graphics.5 isolated gameplay FOV from
file select and overlay cameras, but its fixed diagonal border enlargement still
exposed spinning edges. Graphics.7 reads the actual packed projection, screen-view
and model matrices for the two dedicated transition draws. It intersects viewport
corner rays with each model plane, uniformly enlarges the fade image and extends
only the mask's outer corners. The animated opening, UVs, depth and timing stay
authored. Coverage includes both mask surfaces and the farthest animation depth,
with a small rasterization margin. Original 4:3 vertices remain byte-exact.
Native contracts check complete rotations at 16:9, 21:9 and 32:9 across multiple
camera angles and depths, exact image proportions and unchanged guest state.
The user confirmed that Graphics.7 covers spinning transition edges from title to
file select, and changing the FOV slider leaves file select unchanged.

Graphics.7 also retains each queued renderer upload's source bytes until its copy
finishes. This addresses an access violation observed in asynchronous matrix
upload during the preceding test. The native ownership contract verifies that a
queued copy survives replacement and reallocation of its source vector.

Graphics.9 adds motion interpolation for scrolling sky strips and world billboard
rectangles. World sprites carry their object identity in unused SetPrimDepth
command bits, so the metadata stays with each immutable task snapshot. Anonymous
HUD and menu rectangles retain their authored cadence. Sky matching follows the
nearest periodic copy at texture wrap and includes the observed 640x124 image.
Large jumps, missing owners and incompatible frames reset motion history.
Animated sprites retain current image pixels while their position and size move
between frames; texture animation timing remains authored.

Billboard size and anchor offsets use the same focal-length ratio as gameplay
perspective. Each enhanced world camera reserves projection and view copies
through the game's model-matrix allocator. This prevents later screen cameras
from overwriting its FOV or draw-distance projection before asynchronous decoding.
The original matrix buffers remain available for CPU projection and screen draws.
File select and transition cameras keep their authored projection. Contract tests
cover camera-buffer reuse, allocator bounds, tangent-based sprite scaling,
identity changes, sky wrapping and matching motion across texture strips.

The user confirmed smooth billboard motion in the first Graphics.8 test. That
test exposed the shared camera-buffer overwrite and a shorter sky image missed
by the initial classifier. Graphics.9 addresses both, but the user still observed
sky jitter and stepping on some billboards.

Graphics.10 preserves quarter-pixel geometry for semantic world sprites and sky
strips. The legacy Sprite2D sky no longer receives the RDP rectangle scanline
offset: its sampling span is computed directly from its complete subpixel strip.
This removes a one-texel change when the vertical position crosses an integer
pixel. Matched billboard texture coordinates and primitive depth now follow the
same presentation weight as position and size. Current animation images remain
authored. Semantic world sprites are excluded from HUD scale and safe-margin
transforms. All other rectangle paths keep their existing rasterization.

Contracts cover every quarter-pixel sky phase, intermediate UV endpoints,
negative derivatives, changed orientation, missing motion history and the shared
CPU/shader constant layout. Diagnostics record interpolation weights, UV changes
and matching rejection counts. The user confirmed on 2026-10-01 that Graphics.10
has smooth sky movement and that the remaining billboards move smoothly and stay
correctly aligned when FOV changes. Linux gameplay and full-game completion
remain unverified.


## Menu investigation after Graphics.10

The user reported intermittent whole-image flicker on file select, menus and
results, plus a white background around a results-screen collectible icon.
Graphics.11 fixes a reproduced resize deadlock: the render queue waited for
presentation to finish while holding the configuration mutex needed by the
present queue to finish resizing. The user confirmed resizing works afterward;
menu flicker remained. An attempt to change FPS later produced an access
violation in a graphics-driver worker. The log did not confirm the FPS change
was applied before the fault.

Menu model commands now carry persistent owner/node identities. Secondary
screen cameras retain their own allocated matrix snapshots. A private
Graphics.12 trace showed all 11 tagged file-select models and their camera
matched across 120 consecutive frames. That diagnostic run closed with exit 0.
Several 2D menu draws still lack identities; the remaining menu interpolation
and collectible transparency issues have not been declared resolved.

Graphics.13 protects the main framebuffer while the presentation queue reads
its first image. It releases that lock after the GPU read finishes and before
waiting for additional interpolated frames. Additional targets retain their
existing synchronization. This addresses an unprotected read during split-task
rendering. The user reports that the whole-image flicker remains in this build.
Its validation run also reported D3D12 error 1047: concurrent framebuffer access
from different graphics queues. Validation overhead affected its frame rate.

Graphics.14 extends framebuffer synchronization to CPU uploads during screen
updates. Optional traces now record which completed workload owns each set of
interpolation counters, and Windows validation identifies individual queues.
Menu flicker, menu motion, live FPS switching and collectible transparency still
require validation. Visual and performance tests run without the D3D12 debug
layer; GPU validation is a separate diagnostic run.

Graphics.14 still flickered and missed the target frame rate in the user's
normal test. Its second capture recorded presentations whose workload was only
partly submitted, plus seven presentations whose VI buffer differed from the
interpolation buffer. Graphics.15 publishes Glover presentation events only
after its final full-sync task, using the VI associated with the buffer drawn
by that complete frame. Ordinary VI updates continue to maintain timing history
but cannot publish an intermediate clear, background or model pass. This needs
visual and frame-pacing confirmation. The results icon alpha issue remains open.

Optional private diagnostics use `GLOVER_MENU_TRACE` with `trace.request`,
`dump.request` or `present.request` files to request bounded traces. GPU readback
uses `GLOVER_RENDER_CAPTURE` and `GLOVER_RENDER_CAPTURE_MANUAL` with a
`capture.request` file; manual captures include the full resolved target.
`GLOVER_D3D12_VALIDATION` enables Windows graphics validation when the debug
layer is installed. All these diagnostics are disabled by default, and private
ROM/RDRAM captures are excluded from release packages.


## Graphics.16 frame pacing

Completed frames now select their interpolation source rate from twelve retail
retrace intervals. Zero and delayed intervals remain in the estimate so render
queue catch-up cannot bias 20 Hz gameplay towards 30 Hz. Only the verified
full-sync/end display list counts as a completed frame. The source-rate changes
do not alter game simulation, controller polling or audio clocks.

The host adapter resolves Match Display through SDL. Its requested Manual rate
now reaches RT64 without a second cap to the swap-chain refresh estimate. VSync
and GPU capacity can still limit actual presentations. The private diagnostic
configuration can disable VSync to measure a requested target independently of
monitor detection. See `FRAME_PACING.md` for measurements and limitations.

The user confirmed file select was close to 180 FPS without flicker in the
Graphics.16 cadence test, and reported stable FPS and transitions in a subsequent
run. Those observations preceded the final hidden-cap correction. They do not
constitute complete validation of every results screen or the collectible icon's
alpha.

Set `GLOVER_FRAME_PROFILE` to an existing private directory to collect bounded
`present.csv` and `workload.csv` timing traces. `GLOVER_FRAME_PROFILE_SECONDS`
selects 1-300 seconds (default 90). CSV output is buffered and has no GPU readbacks
or guest-memory dumps. Profiling is disabled when the environment variable is
absent. Never compare performance while building or running GPU validation.
