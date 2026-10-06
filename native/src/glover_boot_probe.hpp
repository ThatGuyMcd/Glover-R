#pragma once
#include "recomp.h"
#include <cstdint>

// /EHsc otherwise assumes a C-linkage function cannot throw. Invalid probe
// arguments deliberately throw, so callers must retain their unwind handlers.
extern "C" void glover_boot_probe_read(std::uint8_t*, recomp_context*) noexcept(false);
