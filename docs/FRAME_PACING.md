# Frame pacing

Glover produces original frames at both 20 Hz and 30 Hz, depending on the
screen and sequence. Interpolation follows that cadence while presenting at
the frame rate selected in Graphics.

At a 180 Hz target, a 20 Hz source needs nine images per original frame and a
30 Hz source needs six. Treating every screen as 20 Hz creates too much work
on 30 Hz screens and can cause uneven presentation.

## Source cadence

`native/src/glover_frame_cadence.hpp` uses the retail VI callback and the last
twelve completed-frame intervals to estimate the source period. Zero and
delayed intervals remain in the sample. A long pause resets the history while
preserving the last known rate.

The checked renderer adapter applies the estimate before the verified
FullSync/EndDL boundary captures the completed workload. Frame history,
framebuffer ownership and interpolation then use that workload's cadence.

## Presentation target

`native/patches/rt64/0049-glover-explicit-presentation-target.patch` passes
Glover's resolved target through the renderer's Manual branch. Match Display
is resolved through SDL. VSync, rendering cost and hardware limits still
apply; loading and resizing can cause short drops.

## Diagnostics and changes

`native/patches/rt64/0048-glover-frame-pacing-diagnostics.patch` provides
optional CPU timing traces for rendering, interpolation, framebuffer locks,
pacing and presentation. It uses bounded, buffered output, performs no GPU
readbacks and is disabled during ordinary launches.

Make changes in the maintained host adapter or checked patches, then use the
normal patch pipeline. Don't edit dependency checkouts or generated game code.
Detailed investigation captures and old validation reports are archived
locally rather than included in the public source.
