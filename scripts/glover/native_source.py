"""Construct a separate, pinned Rocket-R-derived Glover native source tree.

Only maintained host/build source is adapted. No generated game code is copied
or edited. The original reference checkout and an existing Rocket-R installation
are never modified. All rewritten inputs are tied to a full upstream commit.
"""
from __future__ import annotations
import difflib
import hashlib
import posixpath
import json
from pathlib import Path
import re
import shutil
import struct
import zlib
from .rom import atomic_bytes, atomic_json
from .upstream import audit_reference, safe_relative
from .launcher_design import (adapt_launcher_design, adapt_launcher_header, adapt_controls_theme,
                              adapt_launcher_main)
from .native_contract import (ADAPTER_FAMILY, BASE_COMMIT, CONTRACT_PATH,
                              native_metadata, read_record, verify_native_workspace)

class AssemblyError(RuntimeError):
    pass

N64SYM_COMMIT = 'ccf4600f3389f1a84bde23339225cf372fdf7712'
TEST_TARGETS = 'RocketR GloverNativeContractTests GloverLauncherDesignTests RocketRuntimeLogTests RocketControlsTests RocketModsTests RocketSdkServicesTests RocketSdkAudioTests RocketAssetLayersTests GloverCameraModLogicTests GloverSdkRuntimeTests'
OLD_TEST_TARGETS = ('RocketR RocketPresentationTests RocketRuntimeLogTests RocketControlsTests '
                    'RocketControlsUiTests RocketModsTests RocketCameraModTests RocketGraphicsCameraTests')
EXCLUDED_PARTS = {'.git', 'build', 'dist', 'extern', '__pycache__', 'node_modules',
                  'RecompiledFuncs', 'RecompiledRSP', 'RecompiledPatches'}
NO_SOURCE_SUFFIXES = {'.z64','.n64','.v64','.rom','.elf','.exe','.dll','.so','.apk','.appimage',
                      '.jks','.keystore','.pem','.key','.ttf','.otf','.woff','.woff2'}


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise AssemblyError(f'{label}: expected exactly one checked anchor, found {count}. '
                            'No unverified replacement will be applied.')
    return text.replace(old, new, 1)


def between(text: str, first: str, last: str, replacement: str, label: str) -> str:
    if text.count(first) != 1 or text.count(last) != 1:
        raise AssemblyError(label + ': stage boundary changed.')
    a, b = text.index(first), text.index(last)
    if a >= b: raise AssemblyError(label + ': stage order changed.')
    return text[:a] + replacement.rstrip() + '\n\n' + text[b:]


def line_span(text: str, first: str, last: str, label: str) -> tuple[int, int]:
    """Locate two unique complete lines, including their exact indentation.

    A four-space outer PowerShell condition must not also match the suffix of
    an eight-space nested condition. This is intentionally not fuzzy matching.
    """
    positions = []
    for boundary in (first, last):
        if not boundary or "\n" in boundary or "\r" in boundary:
            raise AssemblyError(label + ': boundary must be one nonempty LF-normalized line.')
        matches = list(re.finditer('^' + re.escape(boundary) + '$', text, re.MULTILINE))
        if len(matches) != 1:
            raise AssemblyError(f'{label}: expected one complete boundary line, found {len(matches)}: {boundary!r}')
        positions.append(matches[0].start())
    if positions[0] >= positions[1]:
        raise AssemblyError(label + ': stage order changed.')
    return positions[0], positions[1]


def adapt_prerequisites(text: str) -> str:
    """Adapt stage 1 only; stage 5 has its own legitimate helper invocation."""
    stage1 = "    Banner '1/9 - Windows prerequisites + source integrity'"
    stage2 = "    Banner '2/9 - WSL / Ubuntu decompilation toolchain'"
    start, end = line_span(text, stage1, stage2, 'Windows prerequisite stage')
    body = text[start:end]
    body = once(body, '    Remove-StaleInterpolationExperimentFiles\n', '', 'stage 1 obsolete cleanup')
    body = once(body, '    $DecompHelperPath = Ensure-RocketDecompHelper\n', '', 'stage 1 decomp helper')
    body = once(body, '    Write-Host "Stage-5 helper verified/recreated: $DecompHelperPath" -ForegroundColor DarkGreen\n', '', 'stage 1 decomp helper message')
    first = "    Invoke-Python @((Join-Path $Root 'scripts\\self_check.py'),'--root',$Root)"
    last = '    if (-not (Import-VsEnvironment)) {'
    checks_start, checks_end = line_span(body, first, last, 'stage 1 Glover verification')
    replacement = "    Invoke-Python @((Join-Path $Root 'scripts\\verify_native_tree.py'),'--root',$Root)\n"
    replacement += "    Write-Host 'Glover maintained native source inventory verified.' -ForegroundColor Green\n\n"
    body = body[:checks_start] + replacement + body[checks_end:]
    return text[:start] + body + text[end:]


def rebrand(text: str) -> str:
    # Retain C++ namespace rocket, CMake target RocketR and dependency ABI names.
    # Only visible product text, storage/cache paths and package names change.
    for a,b in (('Rocket: Robot on Wheels','Glover'), ('Rocket: Robot on wheels','Glover'),
                ('Rocket-R','Glover-R'), ('ROCKET-R','GLOVER-R'), ('rocket-r','glover-r')):
        text = text.replace(a,b)
    return text


def adapt_builder(text: str) -> str:
    text = text.replace('\r\n','\n')
    # Remove Rocket's stage-1 call within stage 1. The second, valid call in
    # stage 5 disappears with the entire Rocket ROM/ELF block below. Never
    # weaken once() to replace the first arbitrary match across the file.
    text = adapt_prerequisites(text)
    stage4 = "    Banner '4/9 - Your Rocket US ROM'"
    stage6 = "    Banner '6/9 - N64Recomp and RSPRecomp tools'"
    replacement = r'''    Banner '4/9 - Verified Glover USA ROM'
    if (-not $env:GLOVER_PROJECT_ROOT -or -not $env:GLOVER_CANONICAL_ROM) {
        throw 'Start the outer Glover-R ONE-CLICK-BUILD.cmd, not this generated workspace helper.'
    }
    $GloverProject = $env:GLOVER_PROJECT_ROOT
    $CanonicalRom = $env:GLOVER_CANONICAL_ROM
    if (-not (Test-Path -LiteralPath $CanonicalRom -PathType Leaf)) { throw 'Private Glover ROM is missing.' }
    $PrivateDir = Join-Path $BuildRoot 'private'
    New-Item -ItemType Directory -Force -Path $PrivateDir | Out-Null

    Banner '5/9 - Glover OS symbols and original-byte recompilation inputs'
    $SymbolLog = Join-Path $LogRoot "glover-symbols-$Stamp.log"
    $SymbolReport = Join-Path $PrivateDir 'glover.sdk-symbols.txt'
    $WslRom = Resolve-WslPath $CanonicalRom
    $WslSymbolReport = Resolve-WslPath $PrivateDir
    $symbolExit = Invoke-NativeLogged 'wsl.exe' @('-d',$script:WslDistro,'--exec','/bin/bash',
        "$WslRoot/scripts/build_glover_symbols.sh",$WslRoot,$WslRom,"$WslSymbolReport/glover.sdk-symbols.txt") $SymbolLog
    if ($symbolExit -ne 0) { throw "Glover symbol scan failed (exit $symbolExit). See $SymbolLog" }
    Invoke-Python @((Join-Path $GloverProject 'scripts\prepare_native_inputs.py'),
        '--runtime-root',$Root,'--rom',$CanonicalRom,'--symbols',$SymbolReport)
    $ElfPath = Join-Path $PrivateDir 'glover.us.elf'
    if (-not (Test-Path -LiteralPath $ElfPath)) { throw 'Glover input generation did not produce its checked ELF.' }
'''
    text = between(text, stage4, stage6, replacement, 'Glover ROM and input stages')
    if re.search(r'^\s*\$DecompHelperPath\s*=\s*Ensure-RocketDecompHelper\s*$', text, re.MULTILINE):
        raise AssemblyError('An active Rocket decomp helper call survived the Glover stage replacements.')
    replacement = r'''    Banner '7/9 - Glover CPU and audio RSP recompilation'
    Invoke-Python @((Join-Path $GloverProject 'scripts\generate_native.py'),
        '--runtime-root',$Root,'--n64recomp',$N64Exe,'--rsprecomp',$RspExe)
    $ModTool = Join-Path (Split-Path $N64Exe) 'RecompModTool.exe'
    Invoke-Python @((Join-Path $Root 'scripts\build_glover_mods.py'),'--tool',$ModTool,'--wsl')
    Write-Host 'CPU/RSP generator output verified. Generated game source will remain read-only.' -ForegroundColor Green
'''
    text = between(text, "    Banner '7/9 - Static CPU and RSP recompilation'",
                   "    Banner '8/9 - Selected native platform builds'", replacement, 'Glover code generation')
    old = "'RocketR','RocketPresentationTests','RocketRuntimeLogTests','RocketControlsTests','RocketControlsUiTests','RocketModsTests','RocketCameraModTests','RocketGraphicsCameraTests'"
    new = "'RocketR','GloverNativeContractTests','GloverLauncherDesignTests','RocketRuntimeLogTests','RocketControlsTests','RocketModsTests','RocketSdkServicesTests','RocketSdkAudioTests','RocketAssetLayersTests','GloverCameraModLogicTests','GloverSdkRuntimeTests'"
    text = once(text, old, new, 'native Windows targets')
    # Never advertise old Rocket-only patches as Glover functionality.
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith('Write-Host ') and any(x in line for x in (
            'stable v5/v6', 'Interpolation v35:', 'Interpolation + presentation fix',
            'Attachment/skybox interpolation', 'Rocket runtime policy:',
            'FIXED34 gameplay timing', 'N64 colour dithering v7:')):
            continue
        lines.append(line)
    text = '\n'.join(lines)+'\n'
    # Revision is display provenance, not a duplicated compatibility gate.
    text = text.replace("$BuilderRevision = 'RELEASE-1.0.1'",
                        '$BuilderRevision = "' + ADAPTER_FAMILY + ' / $Version"')
    # Override logging only after upstream definitions. The fixture contains
    # the same complete outer try/banner anchor as the pinned full script.
    text = once(text, 'try {\n    Banner "Rocket-R ${Version}: local static recompilation builder"',
        '. (Join-Path $PSScriptRoot "GloverBuildLogging.ps1")\n\ntry {\n'
        '    Banner "Rocket-R ${Version}: local static recompilation builder"', 'live logging initialization')
    # Keep compiler caches on repeat attempts. Explicit dependency repair may
    # reset these three compiler caches only; private data is never deleted.
    for variable, indent in (('N64Build', '    '), ('HashBuild', '    '), ('WindowsBuild', '        ')):
        old = indent + 'Remove-Item $' + variable + ' -Recurse -Force -ErrorAction SilentlyContinue'
        new = indent + 'if ($RepairDependencies) { Remove-Item $' + variable + ' -Recurse -Force -ErrorAction SilentlyContinue }'
        text = once(text, old, new, 'preserve '+variable+' compiler cache')
    for variable, stage in (('symbolExit','inputs.sdk-symbols'),
                            ('runtimeConfigureExit','windows.configure'),
                            ('runtimeBuildExit','windows.compile-link'), ('runtimeTestExit','windows.tests'),
                            ('linuxExit','linux.x86_64.build-package'), ('linuxArmExit','linux.aarch64.build-package'),
                            ('androidExit','android.arm64.build-package')):
        text = once(text, '$'+variable+' = Invoke-NativeLogged ',
                    '$'+variable+" = Invoke-GloverBuildStage '"+stage+"' ", 'stage reporting '+stage)
    # Compile the actual generated overlay registration first, before the
    # expensive renderer/runtime build; never rewrite the included .inl file.
    anchor = '        $runtimeBuildExit = Invoke-GloverBuildStage '
    guard = ("        $overlayExit = Invoke-GloverBuildStage 'windows.overlay-compile' $NativeCMake "
             "@('--build',$WindowsBuild,'--target','GloverOverlayRegistration','--parallel') $RuntimeLog\n"
             '        if ($overlayExit -ne 0) { throw "Generated overlay registration did not compile. See $RuntimeLog" }\n')
    text = once(text, anchor, guard+anchor, 'early overlay compilation')
    text = once(text, "            Copy-Item (Join-Path $RocketDir '*') $Stage -Recurse -Force",
        r'''            # A compiler cache can retain review executables and local INI files.
            # Ship only the current runtime and its required dependencies/assets.
            foreach ($runtimeFile in @('Glover-R.exe','SDL2.dll','dxcompiler.dll','dxil.dll')) {
                $runtimePath = Join-Path $RocketDir $runtimeFile
                if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
                    throw "Required runtime file is missing: $runtimeFile"
                }
                Copy-Item -LiteralPath $runtimePath -Destination $Stage -Force
            }
            $runtimeSymbols = Join-Path $RocketDir 'Glover-R.pdb'
            if (Test-Path -LiteralPath $runtimeSymbols -PathType Leaf) {
                Copy-Item -LiteralPath $runtimeSymbols -Destination $Stage -Force
            }
            Copy-Item -LiteralPath (Join-Path $RocketDir 'assets') -Destination $Stage -Recurse -Force''',
        'only current Windows runtime files in release')
    return rebrand(text)


def adapt_linux(text: str) -> str:
    first = 'python3 scripts/self_check.py --root .'
    last = 'rm -rf "build/linux-${ROCKET_TARGET_ARCH}"'
    text = between(text, first, last,
        'python3 scripts/verify_native_tree.py --root .\n'
        'python3 scripts/verify_native_generated.py --root .', 'Linux verification')
    text = once(text, OLD_TEST_TARGETS, TEST_TARGETS, 'Linux test targets')
    # A separate cache avoids overwriting Rocket-R's retained platform builds.
    text = text.replace('ROCKET_LINUX_WORK_ROOT','GLOVER_LINUX_WORK_ROOT')
    text = text.replace('WORK="$WORK_BASE/FIXED34-$ARCH"',
                        'WORK="$WORK_BASE/' + ADAPTER_FAMILY + '-$ARCH"')
    return rebrand(text)


def adapt_renderer(text: str) -> str:
    text = once(text,
        '    if (present_count_ == 1) {\n        rocket::start_game_once();\n    }',
        '    // The initial blank VI can be presented while fallback pipelines compile.\n'
        '    // Start the guest only when every pipeline is published as ready; the\n'
        '    // graphics task must never hold the presentation lock waiting for them.\n'
        '    if (application_->rasterShaderCache && application_->rasterShaderCache->shaderUber &&\n'
        '        application_->rasterShaderCache->shaderUber->pipelinesReady()) {\n'
        '        rocket::start_game_once();\n    }', 'safe shader readiness before guest startup')
    text = once(text, '#include "hle/rt64_state.h"',
        '#include "hle/rt64_state.h"\n#include "render/rt64_raster_shader_cache.h"\n#include "common/rt64_glover_configuration.h"\n#include "glover_render_diagnostics.hpp"\n#include "glover_frame_cadence.hpp"',
        'private renderer diagnostics')
    text = once(text, '    update_performance_stats();',
        '    update_performance_stats();\n    glover_capture_frame(*application_);',
        'private GPU capture')
    # Glover completes a frame across several graphics tasks. PresentEarly
    # publishes the clearing task too, causing black flashes and inflated FPS.
    presentation = 'RT64::EnhancementConfiguration::Presentation::Mode::PresentEarly;'
    if text.count(presentation) != 2:
        raise AssemblyError('Renderer presentation mode: expected startup and runtime anchors.')
    text = text.replace(presentation,
        'RT64::EnhancementConfiguration::Presentation::Mode::Console;')
    text = once(text, '        application_ = std::make_unique<RT64::Application>(core, app_config);',
        '        application_ = std::make_unique<RT64::Application>(core, app_config);\n'
        '        // Tasks use private submission snapshots. Keep GPU framebuffer\n'
        '        // results on the GPU: writing them into a disposable snapshot\n'
        '        // makes the next task mistake live black RAM for a CPU update.\n'
        '        application_->emulatorConfig.framebuffer.renderToRAM = false;\n'
        '        RT64::setGloverSplitFrames(true);',
        'snapshot framebuffer ownership')
    # Gameplay is 20 Hz; intro and menus can author 30 Hz. Select source
    # cadence at completed frames using retail retraces, not GPU wall time.
    text = once(text, 'constexpr int kAuthoredPresentationRate = 30;',
                'constexpr int kAuthoredPresentationRate = 20;', 'Glover original frame rate')
    cadence = ('    if (application_->userConfig.refreshRate !=\n'
               '        RT64::UserConfiguration::RefreshRate::Original) {\n'
               '        application_->state->setRefreshRate(kAuthoredPresentationRate);\n    }')
    text = once(text, cadence,
                '    // Source cadence is selected at the verified complete-frame task below.',
                'remove fixed gameplay cadence from menu tasks')
    for a,b in (
        ('RT64::setRocketSkyDitherReduction(settings.sky_dither_reduction);',
         'RT64::setRocketSkyDitherReduction(0.0F);'),
        ('application_->enhancementConfig.f3dex.forceBranch = true;',
         'application_->enhancementConfig.f3dex.forceBranch = false;'),
        ('application_->enhancementConfig.presentation.removeBlackBorders = true;',
         'application_->enhancementConfig.presentation.removeBlackBorders = false;'),
        ('application_->enhancementConfig.rect.fixRectLR = true;',
         'application_->enhancementConfig.rect.fixRectLR = false;'),
        ('    rocket::presentation::TaskIdentityScope identity_scope(\n'
         '        rdram_snapshot, static_cast<std::uint32_t>(task->t.data_ptr));',
         '    // No Rocket-specific presentation sidecar is attached to Glover tasks.'),
        ('        CanonicalViPresentationScope vi_scope(*application_);',
         '        // Preserve Glover VI registers; Rocket overscan normalization is inapplicable.'),
    ):
        text = once(text,a,b,'renderer: '+a[:55])
    # Widen perspective once in RT64; guest guPerspective stays at 4:3.
    pattern = r'rocket::graphics::selected_aspect\(4\.0F / 3\.0F\)'
    n = len(re.findall(pattern, text))
    if n != 2: raise AssemblyError(f'Renderer aspect targets changed: expected 2, got {n}.')
    text = once(text,
        '    const bool hud_widescreen =\n        rocket::graphics::widescreen_active(4.0F / 3.0F);',
        '    const bool hud_widescreen = false; // Original Glover HUD placement.', 'HUD baseline')
    text = once(text,
        'RT64::setRocketHudConfiguration(hud_widescreen ? 1U : 0U, 1.0F, 0.0F);',
        'RT64::setRocketHudConfiguration(2U, 1.0F, 0.0F); // Rectangles already correct their aspect.',
        'avoid duplicate HUD aspect correction')
    text = once(text,
        '    application_->state->rsp->reset();',
        '    if (!glover_first_task_logged_) {\n'
        '        std::fprintf(stderr, "[glover][gfx] first display list ucode=%08X data=%08X bytes=%u\\n",\n'
        '                     task->t.ucode, task->t.data_ptr, task->t.data_size);\n'
        '        glover_first_task_logged_ = true;\n    }\n'
        '    // Glover splits a frame into setup and drawing tasks. The RSP\n'
        '    // viewport, segments and other graphics state survive between them.\n'
        '    // Rebuild workload-local draw, matrix and lighting caches without\n'
        '    // clearing the guest state which those caches describe.\n'
        '    application_->state->resetDrawCall();\n'
        '    auto &rsp = *application_->state->rsp;\n'
        '    rsp.projectionIndex = -1;\n'
        '    rsp.projectionMatrixChanged = true;\n'
        '    rsp.viewportChanged = true;\n'
        '    if (!rsp.modelViewProjInserted) rsp.modelViewProjChanged = true;\n'
        '    rsp.lightsChanged = true;\n'
        '    rsp.fogChanged = true;\n'
        '    rsp.lookAtChanged = true;\n'
        '    rsp.used.reset();\n', 'persistent graphics task state')
    text = once(text, 'std::array<std::uint8_t, 0x40> g_rom_header{};',
                'bool glover_first_task_logged_ = false;\nstd::array<std::uint8_t, 0x40> g_rom_header{};',
                'graphics diagnostic state')
    anchor = ('    application_->processDisplayLists(rdram_snapshot,\n'
              '                                      task->t.data_ptr & 0x03FFFFFF, 0, true);')
    text = once(text, anchor,
        '    const std::uint32_t task_address = task->t.data_ptr & 0x03FFFFFFU;\n'
        '    std::uint32_t frame_commands[4]{};\n'
        '    if (task->t.data_size == 16 && task_address <= 0x007FFFF0U)\n'
        '        std::memcpy(frame_commands, rdram_snapshot + task_address, sizeof frame_commands);\n'
        '    RT64::setGloverTaskFrameEnd(RT64::isGloverFrameEnd(task->t.data_size, frame_commands[0], frame_commands[2]));\n'
        '    if (RT64::isGloverFrameEnd(task->t.data_size, frame_commands[0], frame_commands[2])) {\n'
        '        const auto source_rate = glover::presentation::completed_frame_rate();\n'
        '        application_->state->setRefreshRate(source_rate);\n'
        '        static unsigned previous_source_rate = 0;\n'
        '        if (source_rate != previous_source_rate) {\n'
        '            std::fprintf(stderr, "[glover][cadence] completed-frame source=%u Hz\\n", unsigned(source_rate));\n'
        '            previous_source_rate = source_rate;\n'
        '        }\n'
        '    }\n'
        + anchor + '\n'
        '    glover_capture_task(rdram_snapshot, task_address, task->t.data_size);\n'
        '    static std::uint64_t task_count = 0;\n'
        '    ++task_count;\n'
        '    if (task_count <= 8 || task_count % 241 == 0) {\n'
        '        const auto &queue = *application_->state->ext.workloadQueue;\n'
        '        const auto &work = queue.workloads[queue.previousWriteCursor()];\n'
        '        unsigned calls = 0;\n'
        '        for (unsigned f = 0; f < work.fbPairCount; ++f) calls += work.fbPairs[f].gameCallCount;\n'
        '        unsigned perspective = 0, orthographic = 0;\n'
        '        for (unsigned f = 0; f < work.fbPairCount; ++f) {\n'
        '            const auto &pair = work.fbPairs[f];\n'
        '            for (unsigned p = 0; p < pair.projectionCount; ++p) {\n'
        '                if (pair.projections[p].type == RT64::Projection::Type::Perspective) perspective += pair.projections[p].gameCallCount;\n'
        '                if (pair.projections[p].type == RT64::Projection::Type::Orthographic) orthographic += pair.projections[p].gameCallCount;\n'
        '            }\n        }\n'
        '        std::fprintf(stderr, "[glover][gfx] task=%llu ucode=%08X bytes=%u calls=%u vertices=%u raw=%u fb=%08X source=%u aspect=%u/%.3f scale=%.3f/%.3f\\n",\n'
        '            static_cast<unsigned long long>(task_count), task->t.ucode, task->t.data_size, calls,\n'
        '            work.drawData.vertexCount(), work.drawData.rawTriVertexCount(),\n'
        '            work.fbPairCount ? work.fbPairs[work.fbPairCount - 1].colorImage.address : 0,\n'
        '            work.viOriginalRate, static_cast<unsigned>(application_->userConfig.aspectRatio),\n'
        '            application_->userConfig.aspectTarget,\n'
        '            static_cast<double>(application_->sharedQueueResources->resolutionScale.x),\n'
        '            static_cast<double>(application_->sharedQueueResources->resolutionScale.y));\n'
        '        std::fprintf(stderr, "[glover][gfx] projections perspective=%u ortho=%u m33=%.4f vi=%08X\\n",\n'
        '            perspective, orthographic, static_cast<double>(rsp.projMatrixStack[rsp.projectionMatrixStackSize-1][3][3]),\n'
        '            *application_->core.VI_ORIGIN_REG);\n'
        '        if (task->t.ucode == 0x801BDB40U && calls > 0 && calls < 20) {\n'
        '            for (unsigned f = 0; f < work.fbPairCount; ++f) {\n'
        '                const auto &pair = work.fbPairs[f];\n'
        '                for (unsigned p = 0; p < pair.projectionCount; ++p) {\n'
        '                    for (unsigned d = 0; d < pair.projections[p].gameCallCount; ++d) {\n'
        '                        const auto &call = pair.projections[p].gameCalls[d].callDesc;\n'
        '                        std::fprintf(stderr, "[glover][background] rect=%d,%d,%d,%d scissor=%d,%d,%d,%d aspect=%u\\n",\n'
        '                            call.rect.ulx, call.rect.uly, call.rect.lrx, call.rect.lry,\n'
        '                            call.scissorRect.ulx, call.scissorRect.uly, call.scissorRect.lrx, call.scissorRect.lry, call.rectAspect);\n'
        '                    }\n'
        '                }\n'
        '            }\n'
        '        }\n'
        '        if (perspective > 1) {\n'
        '            for (unsigned f = 0; f < work.fbPairCount; ++f) {\n'
        '                const auto &pair = work.fbPairs[f];\n'
        '                for (unsigned p = 0; p < pair.projectionCount; ++p) {\n'
        '                    const auto &projection = pair.projections[p];\n'
        '                    if (projection.type != RT64::Projection::Type::Perspective) continue;\n'
        '                    const auto i = projection.transformsIndex;\n'
        '                    const auto rect = work.drawData.rspViewports[i].rect(&work.drawData.viewportClipRatios[i*4]);\n'
        '                    std::fprintf(stderr, "[glover][viewport] vp=%d,%d,%d,%d proj=%d,%d,%d,%d pair=%d,%d,%d,%d origin=%u\\n",\n'
        '                        rect.ulx, rect.uly, rect.lrx, rect.lry, projection.scissorRect.ulx, projection.scissorRect.uly,\n'
        '                        projection.scissorRect.lrx, projection.scissorRect.lry, pair.scissorRect.ulx, pair.scissorRect.uly,\n'
        '                        pair.scissorRect.lrx, pair.scissorRect.lry, work.drawData.viewportOrigins[i]);\n'
        '                    break;\n'
        '                }\n'
        '            }\n'
        '        }\n'
        '    }', 'graphics workload diagnostics')
    return rebrand(text)


def adapt_launcher_ui(text: str) -> str:
    text = once(text, '#include "runtime_ui.hpp"',
                '#include "runtime_ui.hpp"\n#include "glover_launcher_profile.hpp"\n#include "glover_launcher_schedule.hpp"',
                'launcher timing include')
    text = once(text,
        '        if (i==page) ImGui::PushStyleColor(ImGuiCol_Button,kWarm);\n'
        '        if (ImGui::Button(labels[static_cast<std::size_t>(i)],{width,58.0F})) page=i;\n'
        '        if (i==page) ImGui::PopStyleColor();',
        '        const bool selected = i == page;\n'
        '        if (selected) ImGui::PushStyleColor(ImGuiCol_Button,kWarm);\n'
        '        if (ImGui::Button(labels[static_cast<std::size_t>(i)],{width,58.0F})) page=i;\n'
        '        if (selected) ImGui::PopStyleColor();',
        'balance sidebar colors when a click changes the current page')
    begin = 'rocket::ui::StartupResult rocket::ui::run_launcher('
    end = 'void rocket::ui::detach('
    if text.count(begin) != 1 or text.count(end) != 1:
        raise AssemblyError('Expected one bounded desktop launcher function.')
    start, stop = text.index(begin), text.index(end)
    launcher = text[start:stop]
    launcher = once(launcher, '    IMGUI_CHECKVERSION();',
        '    SDL_RendererInfo renderer_info{};\n'
        '    SDL_GetRendererInfo(renderer, &renderer_info);\n'
        '    std::fprintf(stderr, "[launcher] renderer=%s flags=0x%X\\n",\n'
        '                 renderer_info.name ? renderer_info.name : "unknown", renderer_info.flags);\n'
        '    glover::launcher::Profile launcher_profile;\n'
        '    glover::launcher::Schedule launcher_schedule;\n'
        '    const auto launcher_frequency = SDL_GetPerformanceFrequency();\n'
        '    const auto launcher_now = [&] {\n'
        '        const auto ticks = SDL_GetPerformanceCounter();\n'
        '        return ticks / launcher_frequency * 1000000 + ticks % launcher_frequency * 1000000 / launcher_frequency;\n'
        '    };\n'
        '    unsigned launcher_display_rate = 60;\n'
        '    const auto update_launcher_display = [&] {\n'
        '        SDL_DisplayMode mode{};\n'
        '        const int display = SDL_GetWindowDisplayIndex(window);\n'
        '        launcher_display_rate = display >= 0 && SDL_GetCurrentDisplayMode(display, &mode) == 0 && mode.refresh_rate > 0\n'
        '            ? unsigned(mode.refresh_rate) : 60U;\n'
        '    };\n'
        '    update_launcher_display();\n'
        '    const bool launcher_software = (renderer_info.flags & SDL_RENDERER_SOFTWARE) != 0;\n'
        '    const auto update_launcher_schedule = [&] {\n'
        '        const auto flags = SDL_GetWindowFlags(window);\n'
        '        const bool visible = (flags & SDL_WINDOW_SHOWN) && !(flags & (SDL_WINDOW_HIDDEN | SDL_WINDOW_MINIMIZED));\n'
        '        launcher_schedule.state(launcher_now(), visible, (flags & SDL_WINDOW_INPUT_FOCUS) != 0,\n'
        '                                launcher_display_rate, launcher_software);\n'
        '    };\n'
        '    Uint64 launcher_waited = 0;\n\n    IMGUI_CHECKVERSION();',
        'launcher renderer identity')
    launcher = once(launcher, '    while (running) {\n        SDL_Event event{};',
        '    while (running) {\n'
        '        update_launcher_schedule();\n'
        '        const auto wait_begin = launcher_profile.now();\n'
        '        const auto wait_ms = launcher_schedule.wait_ms(launcher_now());\n'
        '        if (wait_ms) SDL_WaitEventTimeout(nullptr, int(wait_ms));\n'
        '        launcher_waited += launcher_profile.now() - wait_begin;\n'
        '        const auto frame_begin = launcher_profile.now();\n        SDL_Event event{};',
        'launcher frame begin')
    launcher = once(launcher, '        while (SDL_PollEvent(&event)) {',
        '        while (SDL_PollEvent(&event)) {\n'
        '            if (event.type == SDL_WINDOWEVENT) {\n'
        '                if (event.window.event == SDL_WINDOWEVENT_MOVED || event.window.event == SDL_WINDOWEVENT_DISPLAY_CHANGED)\n'
        '                    update_launcher_display();\n'
        '                if (event.window.event == SDL_WINDOWEVENT_EXPOSED || event.window.event == SDL_WINDOWEVENT_RESTORED ||\n'
        '                    event.window.event == SDL_WINDOWEVENT_FOCUS_GAINED || event.window.event == SDL_WINDOWEVENT_SIZE_CHANGED)\n'
        '                    launcher_schedule.invalidate(launcher_now());\n'
        '            }', 'launcher event wake and display change')
    launcher = once(launcher,
        '        rocket::platform::sample_input();\n\n        ImGui_ImplSDLRenderer2_NewFrame();',
        '        if (!running) break;\n'
        '        update_launcher_schedule();\n'
        '        if (!launcher_schedule.due(launcher_now())) continue;\n'
        '        launcher_schedule.begin(launcher_now());\n'
        '        rocket::platform::sample_input();\n'
        '        const auto input_end = launcher_profile.now();\n\n        ImGui_ImplSDLRenderer2_NewFrame();',
        'launcher input timing')
    launcher = once(launcher, '        ImGui::NewFrame();\n        ApplyStyle();',
                    '        ImGui::NewFrame();', 'launcher style already initialized once')
    launcher = once(launcher, '        ImGui::Render();\n        SDL_SetRenderDrawColor',
        '        ImGui::Render();\n        const auto ui_end = launcher_profile.now();\n        SDL_SetRenderDrawColor',
        'launcher UI timing')
    launcher = once(launcher, '        SDL_RenderPresent(renderer);\n        SDL_Delay(1);',
        '        const auto submit_end = launcher_profile.now();\n'
        '        SDL_RenderPresent(renderer);\n'
        '        const auto present_end = launcher_profile.now();\n'
        '        const auto* draw_data = ImGui::GetDrawData();\n'
        '        launcher_profile.frame(page, frame_begin, input_end, ui_end, submit_end, present_end,\n'
        '            draw_data->TotalVtxCount, draw_data->CmdListsCount, win_w, win_h, SDL_GetWindowFlags(window), launcher_waited);\n'
        '        launcher_waited = 0;',
        'launcher presentation timing')
    return text[:start] + launcher + text[stop:]


def adapt_branding_ui(text: str) -> str:
    # Resolve each requested asset independently. A logo fallback is not a
    # valid substitute for the bundled font or the square desktop icon.
    text = between(text,
        '    const auto probe_root = [&](const std::filesystem::path& root) -> std::filesystem::path {',
        '    if (char* raw = SDL_GetBasePath(); raw != nullptr) {',
        '''    const auto probe_root = [&](const std::filesystem::path& root) -> std::filesystem::path {
        if (root.empty()) return {};
        const std::filesystem::path asset(relative);
        if (auto p = probe(root / asset); !p.empty()) return p;
        const auto source_asset = asset.lexically_relative("assets/ui");
        if (auto p = probe(root / "src/UI" / source_asset); !p.empty()) return p;
        if (auto p = probe(root / asset.filename()); !p.empty()) return p;
        return {};
    };''', 'independent branding asset resolution')
    text = once(text, 'std::vector<unsigned char> ReadRocketLogoBytes() {',
                'std::vector<unsigned char> ReadRocketLogoBytes(bool desktop_icon = false) {',
                'desktop icon asset selection')
    text = once(text,
        '        RuntimeUiAssetPath("assets/ui/Rocket-R-green-full-resolution.png");',
        '        RuntimeUiAssetPath(desktop_icon ? "assets/ui/Rocket-R-green-512x512.png"\n'
        '                                        : "assets/ui/Rocket-R-green-full-resolution.png");',
        'separate square desktop icon from launcher wordmark')
    text = once(text,
        '    if (window == nullptr) return;\n'
        '    const std::vector<unsigned char> encoded = ReadRocketLogoBytes();',
        '    if (window == nullptr) return;\n'
        '    const std::vector<unsigned char> encoded = ReadRocketLogoBytes(true);',
        'window icon preserves wordmark aspect ratio')
    text = text.replace('UiHint("ROCKET: ROBOT ON WHEELS");', 'UiHint("GLOVER RECOMPILED");')
    text = between(text, 'void ConfigureUiFont() {',
        'std::filesystem::path SettingsPath() {',
        r'''void ConfigureUiFont() {
    ImGuiIO& io = ImGui::GetIO();
    constexpr float kUiFontSize = 20.0F;
    const auto bundled = RuntimeUiAssetPath("assets/ui/fonts/Bungee-Regular.ttf");
    ImFont* font = nullptr;
    if (!bundled.empty()) {
        const auto path = PathUtf8(bundled);
        font = io.Fonts->AddFontFromFileTTF(path.c_str(), kUiFontSize);
        if (font != nullptr) {
            std::fprintf(stderr, "[ui] Bungee font: %s (%.0f px)\n", path.c_str(), kUiFontSize);
        }
    }
    if (font == nullptr) {
        ImFontConfig fallback{};
        fallback.SizePixels = kUiFontSize;
        font = io.Fonts->AddFontDefault(&fallback);
        std::fprintf(stderr, "[ui] Bundled Bungee unavailable; using ImGui fallback\n");
    }
    io.FontDefault = font;
    LoadRocketBrandIntoAtlas();
}''', 'approved bundled Bungee font')
    return text


def adapt_linux_packager(text: str) -> str:
    text = once(text,
        'install -m 0644 "$PROJECT_ROOT/src/UI/Rocket-R-green-full-resolution.png" "$APPDIR/usr/bin/assets/ui/Rocket-R-green-full-resolution.png"\n',
        'install -m 0644 "$PROJECT_ROOT/src/UI/Rocket-R-green-full-resolution.png" "$APPDIR/usr/bin/assets/ui/Rocket-R-green-full-resolution.png"\n'
        'install -m 0644 "$PROJECT_ROOT/src/UI/Rocket-R-green-512x512.png" "$APPDIR/usr/bin/assets/ui/Rocket-R-green-512x512.png"\n'
        'mkdir -p "$APPDIR/usr/bin/assets/ui/fonts"\n'
        'install -m 0644 "$PROJECT_ROOT/src/UI/fonts/Bungee-Regular.ttf" "$APPDIR/usr/bin/assets/ui/fonts/Bungee-Regular.ttf"\n'
        'install -m 0644 "$PROJECT_ROOT/src/UI/fonts/OFL.txt" "$APPDIR/usr/bin/assets/ui/fonts/OFL.txt"\n'
        'install -m 0644 "$PROJECT_ROOT/src/UI/fonts/Selawik-Regular.ttf" "$APPDIR/usr/bin/assets/ui/fonts/Selawik-Regular.ttf"\n'
        'install -m 0644 "$PROJECT_ROOT/src/UI/fonts/Selawik-Semibold.ttf" "$APPDIR/usr/bin/assets/ui/fonts/Selawik-Semibold.ttf"\n'
        'install -m 0644 "$PROJECT_ROOT/src/UI/fonts/Selawik-OFL.txt" "$APPDIR/usr/bin/assets/ui/fonts/Selawik-OFL.txt"\n',
        'Linux bundled branding and font assets')
    return rebrand(text)


def adapt_startup_ui(text: str) -> str:
    text = once(text, '#include "hle/rt64_application.h"',
        '#include "hle/rt64_application.h"\n#include "glover_startup_ui.hpp"', 'startup progress UI include')
    text = once(text, '    const bool visible = g_overlay_visible.load(std::memory_order_acquire);',
        '    const bool preparing = glover::startup::preparing(application);\n'
        '    const bool visible = g_overlay_visible.load(std::memory_order_acquire);', 'startup progress visibility')
    text = once(text, '    if (!visible && !diagnostics && mod_hud.empty()) {',
        '    if (!preparing && !visible && !diagnostics && mod_hud.empty()) {', 'retain startup progress presentation')
    text = once(text, '    if(!mod_hud.empty()) {',
        '    glover::startup::draw(application);\n\n    if(!mod_hud.empty()) {', 'draw startup progress')
    return text


def adapt_ui(text: str) -> str:
    text = between(text, '        ImGui::TextUnformatted("Sky dithering reduction");',
                   '        ImGui::TextUnformatted("Replacement texture mip bias");',
                   '', 'omit skybox filtering control')
    text = once(text, '    out << "sky_dither_reduction=" << gx.sky_dither_reduction << \'\\n\';\n',
                '', 'omit skybox setting serialization')
    text = once(text, '            else if (key == "sky_dither_reduction") graphics_extra.sky_dither_reduction = std::stof(value);',
                '            else if (key == "sky_dither_reduction") {} // Ignore legacy skybox settings.',
                'ignore legacy skybox setting')
    text = once(text, 'return "Original 30 FPS";', 'return "Original game frame rate";', 'original rate label')
    text = once(text, 'Original 30 FPS, without frame interpolation.',
                'Original game frame rate, without frame interpolation.', 'original rate hint')
    text = once(text, 'On wide screens, the HUD stays within the centre 16:9 area.',
                'Widescreen expands the 3D view. Menus and HUD retain their original proportions.', 'Glover HUD hint')
    # The Rocket semantic sidecar has no Glover guest bindings. Report actual
    # presentations instead of its permanently zero counters in both overlays.
    text = once(text,
        '        const auto perf = rocket::graphics::performance_stats();\n'
        '        const auto coverage = rocket::presentation::coverage_stats();',
        '        const auto perf = rocket::graphics::performance_stats();',
        'remove detailed sidecar query')
    first = '        ImGui::Text("Identified interpolation bindings: %llu",'
    last = '        UiHint("When a match between frames is uncertain, interpolation is skipped for that item.");'
    text = between(text, first, last, '', 'Glover detailed interpolation stats')
    start = '        const auto coverage = rocket::presentation::coverage_stats();'
    end = '                    static_cast<unsigned long long>(coverage.sidecar_mismatches));'
    text = between(text, start, end,
        '        const auto perf = rocket::graphics::performance_stats();\n'
        '        ImGui::Text("Interpolated presentations: %llu",\n'
        '                    static_cast<unsigned long long>(perf.interpolated_presents));\n'
        '        ImGui::Text("Presentation target: %d Hz", perf.target_rate);', 'Glover interpolation overlay')
    # between() retains its last boundary; remove that consumed closing line.
    text = once(text, end + '\n', '', 'remove old overlay tail')
    return rebrand(text)


def adapt_graphics_settings(text: str) -> str:
    # Keep the shared settings store, presets and telemetry. Rocket camera
    # memory layouts must never be callable from Glover's guest hooks.
    text = between(text, 'constexpr std::uint32_t kRdramStart = 0x80000000U;',
                   '} // namespace',
                   'constexpr float kPi = 3.14159265358979323846F;\n'
                   'constexpr float kRadToDeg = 180.0F / kPi;\n'
                   'constexpr float kDegToRad = kPi / 180.0F;', 'remove Rocket camera layout helpers')
    anchor = 'extern "C" void rocket_graphics_camera_begin'
    if text.count(anchor) != 1 or len(re.findall(r'extern "C" void rocket_graphics_', text)) != 3:
        raise AssemblyError('Rocket graphics guest hook boundaries changed.')
    text = text[:text.index(anchor)]
    text = once(text,
        '    normalized.sky_dither_reduction = std::isfinite(normalized.sky_dither_reduction)\n'
        '        ? std::clamp(normalized.sky_dither_reduction, 0.0F, 1.0F) : 0.0F;',
        '    normalized.sky_dither_reduction = 0.0F; // Glover excludes skybox filtering.',
        'neutral skybox setting')
    for field, low, high, fallback in (
        ('custom_aspect', '1.0F', '4.0F', '16.0F / 9.0F'),
        ('mip_lod_bias', '-2.0F', '2.0F', '-0.25F'),
        ('fov_offset_degrees', '-20.0F', '40.0F', '0.0F'),
        ('post_process_strength', '0.0F', '100.0F', '70.0F'),
    ):
        old = f'    normalized.{field} = std::clamp(normalized.{field}, {low}, {high});'
        new = f'    normalized.{field} = std::isfinite(normalized.{field})\n        ? std::clamp(normalized.{field}, {low}, {high}) : {fallback};'
        text = once(text, old, new, 'finite '+field)
    text = once(text,
        '    normalized.draw_distance_multiplier = static_cast<float>(std::clamp(static_cast<int>(std::lround(normalized.draw_distance_multiplier)), 1, 6));',
        '    normalized.draw_distance_multiplier = std::isfinite(normalized.draw_distance_multiplier)\n'
        '        ? std::round(std::clamp(normalized.draw_distance_multiplier, 1.0F, 6.0F)) : 1.0F;', 'finite draw distance')
    return rebrand(text)


def adapt_main(text: str) -> str:
    text = once(text, 'your Rocket US ROM', 'your Glover USA ROM', 'Glover ROM help')
    text = once(text, '        if (task->t.ucode != rocket::kAudioUcodeVram) {',
        '        if ((task->t.ucode & 0x1FFFFFFFU) != (rocket::kAudioUcodeVram & 0x1FFFFFFFU)) {',
        'audio physical address comparison')
    # Preserve the public package importer; Glover identity is validated by
    # the maintained library before any package reaches runtime staging.
    text = once(text, '#include <exception>', '#include <exception>\n#include <stdexcept>\n#include "glover_frame_cadence.hpp"', 'main standard include')
    text = once(text, '    events_callbacks.vi_callback = nullptr;',
        '    events_callbacks.vi_callback = glover::presentation::on_retrace;', 'retail retrace cadence observation')
    text = once(text, '        if (task->t.data_size == 0) return empty_audio_task;',
        '        static bool audio_logged = false;\n'
        '        if (!audio_logged) { std::fprintf(stderr, "[glover][audio] first verified audio task bytes=%u\\n", task->t.data_size); audio_logged = true; }\n'
        '        if (task->t.data_size == 0) return empty_audio_task;', 'first audio task log')
    return rebrand(text)


def scanner_patch() -> bytes:
    # Complete checked hunks from pinned src/n64sym.cpp. Preserve relocation
    # aliases and positive signature sizes so Python can reject ambiguities.
    return b'''diff --git a/src/n64sym.cpp b/src/n64sym.cpp
--- a/src/n64sym.cpp
+++ b/src/n64sym.cpp
@@ -291,7 +291,7 @@ void CN64Sym::DumpResults()
     default:
         for(auto& result : m_Results)
         {
-            Output("%08X %s\\n", result.address, result.name);
+            Output("%08X %s %08X\\n", result.address, result.name, result.size);
         }
         break;
     }
@@ -861,7 +861,9 @@ bool CN64Sym::AddResult(search_result_t result)
 
     for(auto& otherResult : m_Results)
     {
-        if(otherResult.address == result.address)
+        if(otherResult.address == result.address &&
+           otherResult.size == result.size &&
+           strcmp(otherResult.name, result.name) == 0)
         {
             return false; // already have
         }
'''


def placeholder_png() -> bytes:
    """An original, font-free geometric G placeholder, not a game asset."""
    size=256; pixels=bytearray()
    glyph=['01110','11000','11000','11011','11001','11001','01110']
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            gx,gy=(x-48)//32,(y-16)//32
            on=0<=gx<5 and 0<=gy<7 and glyph[gy][gx]=='1'
            pixels.extend((235,241,248,255) if on else (30,47,65,255))
    def chunk(tag,data): return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',size,size,8,6,0,0,0))+
            chunk(b'IDAT',zlib.compress(bytes(pixels),9))+chunk(b'IEND',b''))


def build_payload(project: Path, reference: Path) -> tuple[dict[str,bytes],dict]:
    lock=json.loads((project/'config/upstreams.lock.json').read_text())
    if lock['rocket_base']['commit'] != BASE_COMMIT:
        raise AssemblyError('The source contract and pinned Rocket-R baseline disagree.')
    audit=audit_reference(reference,lock['rocket_base'])
    payload:dict[str,bytes]={}
    for path in sorted(reference.rglob('*')):
        rel=path.relative_to(reference)
        if any(p in EXCLUDED_PARTS for p in rel.parts): continue
        if path.is_symlink(): raise AssemblyError('Symlinked upstream entry refused: '+str(rel))
        if not path.is_file(): continue
        if path.suffix.lower() in NO_SOURCE_SUFFIXES: continue
        name=rel.as_posix()
        # Never activate or distribute Rocket guest-mod examples/policies.
        if name.startswith('modding/') or name.startswith('runtime-recomp/') or name.startswith('generated/') or name.startswith('roms/'):
            continue
        data=path.read_bytes()
        if path.suffix.lower() in {'.cpp','.hpp','.h','.ps1','.sh','.cmd','.java','.xml','.gradle','.properties','.desktop'}:
            try:
                text=data.decode('utf-8-sig').replace('\r\n','\n')
            except UnicodeDecodeError: text=None
            if text is not None:
                if name=='scripts/OneClickBuild.ps1': text=adapt_builder(text)
                elif name=='Build-Linux.sh': text=adapt_linux(text)
                elif name=='scripts/package_appimage.sh': text=adapt_linux_packager(text)
                elif name=='src/rt64_renderer.cpp': text=adapt_renderer(text)
                elif name=='src/runtime_ui.cpp': text=adapt_launcher_design(adapt_ui(adapt_launcher_ui(adapt_branding_ui(text))), once, between)
                elif name=='src/graphics_enhancements.cpp': text=adapt_graphics_settings(text)
                elif name=='src/main.cpp': text=adapt_launcher_main(adapt_main(text), once)
                elif name=='src/runtime_ui.hpp': text=adapt_launcher_header(text, once)
                elif name=='src/controls_studio.cpp': text=adapt_controls_theme(rebrand(text), once)
                else: text=rebrand(text)
                # Android package isolation; JNI/class identifiers are changed
                # consistently throughout packaging and host sources.
                text=text.replace('com.thatguymcd.rocketr','com.thatguymcd.gloverr')
                text=text.replace('com.thatguymcd.rocket','com.thatguymcd.glover')
                text=text.replace('org.rocket_recomp','org.glover_recomp')
                text=text.replace('com.rocketret.rocketr','com.thatguymcd.gloverr')
                text=text.replace('com/rocketret/rocketr','com/thatguymcd/gloverr')
                text=text.replace('com\\rocketret\\rocketr','com\\thatguymcd\\gloverr')
                text=text.replace('com_rocketret_rocketr','com_thatguymcd_gloverr')
                if path.suffix.lower()=='.java':
                    text=text.replace('rocket.us.z64','glover.us.z64')
                    if path.name=='MainActivity.java':
                        text=once(text, '        mods.setText("MODS");',
                            '        mods.setText("MODS â€” NOT AVAILABLE IN THIS BOOT CANDIDATE");\n        mods.setEnabled(false);',
                            'Android code-mod UI restriction')
                data=text.encode('utf-8')
        if not name.startswith('patches/'):
            name=rebrand(name).replace('com/rocketret/rocketr','com/thatguymcd/gloverr')
        payload[name]=data
    for required in ('src/main.cpp','src/runtime_ui.cpp','src/rt64_renderer.cpp','Build-Linux.sh'):
        if required not in payload: raise AssemblyError('Pinned base is missing '+required)
    for path in sorted((project/'native').rglob('*')):
        if not path.is_file(): continue
        name=path.relative_to(project/'native').as_posix()
        if name in {'src/mod_runtime.cpp','src/mod_ui.cpp'}: name='src/mods/'+path.name
        payload[name]=path.read_bytes()
    payload['runtime-recomp/glover.us.recomp-policy.json']=(project/'runtime-recomp/glover.us.recomp-policy.json').read_bytes()
    if (project/'native/src/glover_mod_capture.inl').is_file():
        from .mods_adapters import adapt_ui as mod_ui, adapt_header as mod_header, adapt_platform as mod_platform
        for name,adapter in (('src/runtime_ui.cpp',mod_ui),('src/runtime_ui.hpp',mod_header),('src/platform.cpp',mod_platform)):
            text=payload[name].decode('utf-8')
            text=adapter(text,once,between) if name.endswith('runtime_ui.cpp') else adapter(text,once)
            payload[name]=text.encode('utf-8')
        payload['src/runtime_ui.cpp'] = adapt_startup_ui(payload['src/runtime_ui.cpp'].decode('utf-8')).encode('utf-8')
    # Install exactly the same contract module used by this assembler. No
    # separate release-specific validator is maintained in the native tree.
    payload[CONTRACT_PATH] = Path(__file__).with_name('native_contract.py').read_bytes()
    payload['scripts/glover/overlay_validation.py'] = Path(__file__).with_name('overlay_validation.py').read_bytes()
    payload['scripts/glover/__init__.py'] = Path(__file__).with_name('__init__.py').read_bytes()
    # All dependency patches from Rocket-R retain their original bytes/order.
    deps=json.loads((reference/'dependencies.lock.json').read_text())
    deps['dependencies']=[d for d in deps['dependencies'] if d['name']!='rocket-decomp']
    deps['dependencies'].append({'name':'n64sym','repository':'https://github.com/shygoo/n64sym.git',
        'commit':N64SYM_COMMIT,'destination':'extern/n64sym','recursive':False,
        'purpose':'Signature/relocation evidence for Glover OS symbol mapping'})
    payload['dependencies.lock.json']=(json.dumps(deps,indent=2)+'\n').encode()
    patches=json.loads((reference/'patches/manifest.json').read_text())
    patch=scanner_patch(); patch_name='patches/n64sym/0001-preserve-symbol-size-and-alias-evidence.patch'
    payload[patch_name]=patch
    patches['dependencies'].append({'name':'n64sym','repositoryPath':'extern/n64sym',
        'expectedCommit':N64SYM_COMMIT,'patches':[{'path':patch_name,
        'sha256':hashlib.sha256(patch).hexdigest(),
        'purpose':'Retain signature sizes and conflicting aliases instead of first-match wins'}]})
    payload['patches/manifest.json']=(json.dumps(patches,indent=2)+'\n').encode()
    # Append maintained Glover patches after the unchanged, pinned base patches.
    for directory, dependency, purpose in (
        ('rt64', 'RT64', 'Decode Glover legacy Sprite2D tasks with their F3D command dispatch'),
        ('n64-modern-runtime', 'N64ModernRuntime', 'Provide the graphics snapshot address aperture used by the RDP'),
    ):
        additions = sorted((project/'native/patches'/directory).glob('*.patch'))
        if not additions:
            continue
        dep_patches = next(d for d in patches['dependencies'] if d['name'] == dependency)
        base_patch_paths = {p['path'] for p in dep_patches['patches']}
        for path in additions:
            name = 'patches/' + directory + '/' + path.name
            if name in base_patch_paths:
                raise AssemblyError('Glover dependency patch would replace a pinned base patch: '+name)
            data = path.read_bytes()
            payload[name] = data
            dep_patches['patches'].append({'path': name,
                'sha256': hashlib.sha256(data).hexdigest(), 'purpose': purpose})
    payload['patches/manifest.json']=(json.dumps(patches,indent=2)+'\n').encode()
    # Maintained user-supplied branding takes precedence over the original
    # geometric placeholder. The font reference image is never a payload asset.
    brand_directory = project/'native/src/UI'
    brand_image = brand_directory/'Glover-R-green-full-resolution.png'
    if brand_image.is_file():
        required_brand = ('Glover-R-green-512x512.png', 'Glover-R-green.ico')
        if any(not (brand_directory/name).is_file() for name in required_brand):
            raise AssemblyError('Maintained branding needs its square desktop PNG and Windows ICO.')
        png = brand_image.read_bytes()
        desktop_png = (brand_directory/'Glover-R-green-512x512.png').read_bytes()
        ico = (brand_directory/'Glover-R-green.ico').read_bytes()
    else:
        png = desktop_png = placeholder_png()
        ico = struct.pack('<3H',0,1,1)+struct.pack('<4B2H2I',0,0,0,0,1,32,len(png),22)+png
    payload['src/UI/Glover-R-green-full-resolution.png']=png
    payload['src/UI/Glover-R-green-512x512.png']=desktop_png
    for name in list(payload):
        if name.startswith('packaging/android/') and name.endswith('.png') and ('rocket' in name.lower() or 'ic_launcher' in name):
            payload[name]=desktop_png
    for name in list(payload):
        if name.startswith('src/UI/') and name.lower().endswith('.ico'): payload[name]=ico
    payload['VERSION']=(project/'VERSION').read_bytes()
    # Runtime packages must not contain the old Rocket gameplay claims.
    # The maintained guide lives under docs/, but native copies also live at
    # the package root and in nested docs. Resolve its links for each location.
    release_guide=(project/'docs/NATIVE-README.md').read_text(encoding='utf-8')
    def release_readme(name: str) -> bytes:
        directory=posixpath.dirname(name) or '.'
        text=release_guide
        for guide in ('GRAPHICS.md','MODDING.md'):
            target=posixpath.relpath('docs/'+guide,directory)
            text=text.replace('('+guide+')','('+target+')')
        return text.encode('utf-8')
    for name in ('README.md','CHANGELOG.md'):
        payload[name]=release_readme(name)
    for name in list(payload):
        if name.startswith('docs/') and name.lower().endswith('.md'):
            payload[name]=release_readme(name)
    for guide in ('BRANDING.md', 'GRAPHICS.md', 'FRAME_PACING.md', 'MODDING.md'):
        if (project/'docs'/guide).is_file():
            # Windows resolves names without case, Linux does not. Replace the
            # inherited spelling rather than creating two different guides.
            for inherited in list(payload):
                if inherited.casefold() == ('docs/'+guide).casefold():
                    del payload[inherited]
            payload['docs/'+guide]=(project/'docs'/guide).read_bytes()
    # Preserve legal notices and credits; add provenance instead of altering them.
    payload['THIRD_PARTY.md']=(b'# Glover-R component provenance\n\nThe original Rocket-R notices below describe the inherited host baseline.\nRocket guest decompilation is not used by Glover; its ROM/ELF pipeline is separate.\n\n'+(reference/'THIRD_PARTY.md').read_bytes())+(
        '\n\nGlover-R boot integration: derived from Rocket-R commit '+lock['rocket_base']['commit']+
        '. Glover layout research references Rainchus/Glover. n64sym by shygoo (MIT) is used only at build time.\n').encode()
    if 'src/UI/fonts/Bungee-Regular.ttf' in payload:
        payload['THIRD_PARTY.md'] += (
            '\n\nBungee Regular: Copyright 2023 The Bungee Project Authors '
            '(https://github.com/djrrb/Bungee). Licensed under the SIL Open Font License 1.1. '
            'The unmodified font and full licence are bundled in assets/ui/fonts/; '
            'the release documentation also includes licenses/bungee/OFL.txt. '
            'Source: https://github.com/google/fonts/tree/main/ofl/bungee\n').encode()
    if 'src/UI/fonts/Selawik-Regular.ttf' in payload:
        payload['THIRD_PARTY.md'] += (
            '\n\nSelawik Regular and Semibold: Copyright 2015 Microsoft Corporation. '
            'Licensed under the SIL Open Font License 1.1. Unmodified release 1.01 TTFs; '
            'source: https://github.com/microsoft/Selawik/releases/tag/1.01 . '
            'Full notice: assets/ui/fonts/Selawik-OFL.txt and licenses/selawik/OFL.txt.\n').encode()
    metadata = native_metadata((project/'VERSION').read_text(encoding='utf-8').strip())
    return payload,{**metadata,'base_audit':audit,'game_boot_verified':False}


def assemble(project: Path, reference: Path, output: Path) -> dict:
    project=project.resolve(); reference=reference.resolve()
    expected=project/'build/native-src'
    if output.is_symlink() or output.resolve()!=expected.resolve():
        raise AssemblyError('Native assembly destination must be this project\'s build/native-src.')
    payload,audit=build_payload(project,reference)
    owner=output/'GLOVER-NATIVE-SOURCE.json'
    previous={}
    if output.exists():
        if not owner.is_file(): raise AssemblyError('Existing native workspace has no ownership record; nothing was overwritten.')
        try:
            # Intact Boot.1/2/3 workspaces migrate automatically, with their old
            # hashes verified first. Private builds/ROMs/caches are not touched.
            verify_native_workspace(output, allow_legacy=True)
            previous=read_record(output)['files']
            # A maintained guide may change only its spelling. On Windows the
            # two paths identify the same verified owned file; do not mistake
            # it for an unowned file or delete it during stale-file cleanup.
            previous_spelling={name.casefold():name for name in previous}
            for name in payload:
                old=previous_spelling.get(name.casefold())
                if old and old!=name:
                    path=safe_relative(output,name)
                    if path.exists() and path.samefile(safe_relative(output,old)):
                        previous[name]=previous.pop(old)
        except (OSError, ValueError, KeyError) as error:
            raise AssemblyError(str(error)) from error
    output.mkdir(parents=True,exist_ok=True)
    for name,data in payload.items():
        path=safe_relative(output,name)
        if path.exists() and name not in previous:
            if path.read_bytes()!=data: raise AssemblyError('Unowned native source would be overwritten: '+name)
    for name,data in payload.items():
        path = safe_relative(output,name)
        # Keep timestamps for identical maintained files so Ninja can reuse
        # existing objects. Changed source is still atomically replaced.
        if not path.is_file() or path.read_bytes() != data:
            atomic_bytes(path,data)
    for name in previous.keys()-payload.keys(): safe_relative(output,name).unlink()
    files={name:hashlib.sha256(data).hexdigest() for name,data in sorted(payload.items())}
    record={**audit,'files':files}
    atomic_json(owner,record)
    inventory_check = verify_native_workspace(output)
    return {'native_source_root':str(output),'source_files':len(files),
            **audit,'source_inventory':inventory_check}
