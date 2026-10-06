#include "glover_boot_probe.hpp"
#include <cstdint>
#include <cstdio>
#include <stdexcept>

// The checked call at 80139E44 probes 16 words at cart offset 00FFB000.
// The 8 MiB ROM has no data there, and the resulting stack buffer is unused.
// Do not allow the host osPiReadIo implementation to read past its ROM vector.
// Only this exact startup call is redirected; normal cartridge I/O is intact.
extern "C" void glover_boot_probe_read(std::uint8_t* rdram,recomp_context* ctx) noexcept(false) {
    if (!rdram || !ctx) throw std::runtime_error("Null Glover startup context");
    const auto cart = static_cast<std::uint32_t>(ctx->r4);
    const auto guest = static_cast<std::uint32_t>(ctx->r5);
    const auto out = guest & 0x1FFFFFFFU;
    if (!rdram || (cart < 0x00FFB000U || cart >= 0x00FFB040U || (cart & 3U)) ||
        (guest & 0xE0000000U) != 0x80000000U || out > 0x800000U-4U || (out & 3U))
        throw std::runtime_error("Unexpected arguments to the Glover startup ROM-bus probe");
    // Native RDRAM is word-swapped. All-one bytes are endian-independent.
    rdram[out]=rdram[out+1]=rdram[out+2]=rdram[out+3]=0xFFU;
    ctx->r2=static_cast<gpr>(static_cast<std::int64_t>(-1));
    if (cart==0x00FFB000U)
        std::fprintf(stderr,"[glover][boot] out-of-cartridge identification probe safely returned an error; result buffer unused\n");
}
