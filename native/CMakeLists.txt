cmake_minimum_required(VERSION 3.22.1)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION")
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" ROCKET_R_VERSION LIMIT_COUNT 1)
if(NOT ROCKET_R_VERSION MATCHES "^([0-9]+[.][0-9]+[.][0-9]+)([-+][0-9A-Za-z._-]+)?$")
    message(FATAL_ERROR "Invalid VERSION")
endif()
project(GloverR VERSION ${CMAKE_MATCH_1} LANGUAGES C CXX)
set(ROCKET_SOURCE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
set(CMAKE_C_STANDARD 17)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(RUNTIME "${ROCKET_SOURCE_ROOT}/extern/n64-modern-runtime")
set(RT64_ROOT "${ROCKET_SOURCE_ROOT}/extern/rt64")
set(CPU "${ROCKET_SOURCE_ROOT}/runtime-recomp/RecompiledFuncs")
set(RSP "${ROCKET_SOURCE_ROOT}/runtime-recomp/RecompiledRSP")
foreach(f "${RUNTIME}/CMakeLists.txt" "${RT64_ROOT}/CMakeLists.txt"
    "${ROCKET_SOURCE_ROOT}/generated/bootstrap.generated.hpp"
    "${ROCKET_SOURCE_ROOT}/generated/rom_identity.generated.hpp" "${CPU}/recomp_overlays.inl")
    if(NOT EXISTS "${f}")
        message(FATAL_ERROR "Missing ${f}. Run ONE-CLICK-BUILD.cmd first.")
    endif()
endforeach()
file(GLOB CPU_C CONFIGURE_DEPENDS "${CPU}/*.c")
file(GLOB CPU_CPP CONFIGURE_DEPENDS "${CPU}/*.cpp")
file(GLOB RSP_CPP CONFIGURE_DEPENDS "${RSP}/*.cpp")
if((NOT CPU_C AND NOT CPU_CPP) OR NOT RSP_CPP)
    message(FATAL_ERROR "CPU/RSP generation did not produce sources")
endif()
if(WIN32)
    add_compile_definitions(NOMINMAX _DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR)
endif()
set(RT64_STATIC TRUE CACHE BOOL "" FORCE)
set(RT64_SDL_WINDOW_VULKAN TRUE CACHE BOOL "" FORCE)
add_compile_definitions(HLSL_CPU GLOVER_R_BOOT_CANDIDATE=1)
add_subdirectory("${RT64_ROOT}" "${CMAKE_BINARY_DIR}/rt64")
# Deliberately NO RT64_ROCKET_SAFE_AREA_CROP definition for Glover.
add_subdirectory("${RUNTIME}" "${CMAKE_BINARY_DIR}/N64ModernRuntime")
add_library(RocketModsCore STATIC src/mods/mod_library.cpp src/mods/sdk_services.cpp
    src/mods/sdk_world.cpp src/mods/sdk_audio.cpp src/mods/asset_layers.cpp)
target_include_directories(RocketModsCore PUBLIC "${ROCKET_SOURCE_ROOT}/src" "${RUNTIME}/thirdparty"
    "${ROCKET_SOURCE_ROOT}/modding/include")
target_link_libraries(RocketModsCore PUBLIC miniz)
add_library(RocketRecompiled STATIC ${CPU_C} ${CPU_CPP})
target_include_directories(RocketRecompiled PRIVATE "${CPU}" "${RUNTIME}/N64Recomp/include"
    "${RUNTIME}/ultramodern/include" "${RUNTIME}/librecomp/include")
if(WIN32)
    target_compile_options(RocketRecompiled PRIVATE /clang:-fno-strict-aliasing
        -Wno-unused-variable -Wno-unused-but-set-variable
        $<$<COMPILE_LANGUAGE:C>:-Wno-implicit-function-declaration>
        $<$<COMPILE_LANGUAGE:C>:-Wno-incompatible-pointer-types>
        $<$<COMPILE_LANGUAGE:C>:-Wno-int-conversion>)
else()
    target_compile_options(RocketRecompiled PRIVATE -fvisibility=hidden -fno-strict-aliasing
        -Wno-unused-variable -Wno-unused-but-set-variable -Wno-builtin-declaration-mismatch
        $<$<COMPILE_LANGUAGE:C>:-Wno-implicit-function-declaration>
        $<$<COMPILE_LANGUAGE:C>:-Wno-incompatible-pointer-types>
        $<$<COMPILE_LANGUAGE:C>:-Wno-int-conversion>)
endif()
# Compile the real generated overlay-table consumer before the full game.
# Only this maintained build graph changes; the generated .inl stays read-only.
add_library(GloverOverlayRegistration OBJECT src/register_overlays.cpp)
target_include_directories(GloverOverlayRegistration PRIVATE
    "${ROCKET_SOURCE_ROOT}/src" "${RUNTIME}/N64Recomp/include"
    "${RUNTIME}/librecomp/include" "${RUNTIME}/ultramodern/include")
set_target_properties(GloverOverlayRegistration PROPERTIES POSITION_INDEPENDENT_CODE ON)
set(HOST_SOURCES
    src/main.cpp src/platform.cpp src/runtime_input.cpp src/binding_capture.cpp src/controls_studio.cpp
    src/graphics_enhancements.cpp src/runtime_ui.cpp src/rt64_renderer.cpp src/renderer_snapshot.cpp
    src/presentation_identity.cpp src/render_telemetry_compat.cpp src/widescreen_culling.cpp
    src/game_registration.cpp src/glover_boot_probe.cpp src/glover_graphics.cpp src/mods/mod_runtime.cpp src/mods/mod_ui.cpp
    src/mods/sdk_runtime.cpp
    src/mods/mod_android.cpp src/crash_handler.cpp src/runtime_log.cpp
    "${RT64_ROOT}/src/contrib/imgui/backends/imgui_impl_sdlrenderer2.cpp" ${RSP_CPP})
if(ANDROID)
    add_library(RocketR SHARED ${HOST_SOURCES})
    set_target_properties(RocketR PROPERTIES OUTPUT_NAME main PREFIX lib LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
else()
    add_executable(RocketR ${HOST_SOURCES})
    set_target_properties(RocketR PROPERTIES OUTPUT_NAME "Glover-R" RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
    foreach(config Debug Release RelWithDebInfo MinSizeRel)
        string(TOUPPER "${config}" upper)
        set_target_properties(RocketR PROPERTIES RUNTIME_OUTPUT_DIRECTORY_${upper} "${CMAKE_BINARY_DIR}/bin/${config}")
    endforeach()
    if(WIN32)
        enable_language(RC)
        target_sources(RocketR PRIVATE src/glover-r.rc)
        set_target_properties(RocketR PROPERTIES WIN32_EXECUTABLE TRUE)
        target_link_options(RocketR PRIVATE /ENTRY:mainCRTStartup)
    endif()
endif()
target_sources(RocketR PRIVATE $<TARGET_OBJECTS:GloverOverlayRegistration>)
target_include_directories(RocketR PRIVATE
    "${ROCKET_SOURCE_ROOT}/src" "${ROCKET_SOURCE_ROOT}/generated" "${RUNTIME}/N64Recomp/include"
    "${RUNTIME}/ultramodern/include" "${RUNTIME}/librecomp/include" "${RUNTIME}/thirdparty" "${RSP}"
    "$<TARGET_PROPERTY:rt64,INCLUDE_DIRECTORIES>" "${RT64_ROOT}/src" "${RT64_ROOT}/src/include"
    "${RT64_ROOT}/src/contrib" "${RT64_ROOT}/src/contrib/hlslpp/include" "${RT64_ROOT}/src/contrib/plume"
    "${RT64_ROOT}/src/contrib/imgui" "${RT64_ROOT}/src/contrib/mupen64plus-core/src/api"
    "${RT64_ROOT}/src/contrib/nativefiledialog-extended/src/include" "${CMAKE_BINARY_DIR}/src")
target_compile_definitions(RocketR PRIVATE RT64_SDL_WINDOW_VULKAN=1
    ROCKET_R_VERSION_MAJOR=${PROJECT_VERSION_MAJOR} ROCKET_R_VERSION_MINOR=${PROJECT_VERSION_MINOR}
    ROCKET_R_VERSION_PATCH=${PROJECT_VERSION_PATCH} ROCKET_R_VERSION="${ROCKET_R_VERSION}")
if(WIN32 AND CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    target_compile_options(RocketR PRIVATE /clang:-msse4.1)
elseif(NOT MSVC AND CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$")
    target_compile_options(RocketR PRIVATE -msse4.1)
endif()
target_link_libraries(RocketR PRIVATE RocketRecompiled ultramodern librecomp rt64 RocketModsCore)
if(WIN32)
    set(SDLBASE "${RT64_ROOT}/src/contrib/mupen64plus-win32-deps/SDL2-2.26.3")
    target_include_directories(RocketR PRIVATE "${SDLBASE}/include")
    target_link_directories(RocketR PRIVATE "${SDLBASE}/lib/x64")
    target_link_libraries(RocketR PRIVATE SDL2 user32 shell32 comdlg32 dbghelp dxgi winmm)
    foreach(pair "${SDLBASE}/lib/x64/SDL2.dll" "${RT64_ROOT}/src/contrib/dxc/bin/x64/dxcompiler.dll" "${RT64_ROOT}/src/contrib/dxc/bin/x64/dxil.dll")
        add_custom_command(TARGET RocketR POST_BUILD COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${pair}" "$<TARGET_FILE_DIR:RocketR>" VERBATIM)
    endforeach()
elseif(ANDROID)
    if(NOT TARGET SDL2)
        message(FATAL_ERROR "Use the inherited SDL2 Android JNI project")
    endif()
    target_link_libraries(RocketR PRIVATE SDL2 android log dl)
else()
    find_package(SDL2 REQUIRED)
    target_include_directories(RocketR PRIVATE ${SDL2_INCLUDE_DIRS})
    target_link_libraries(RocketR PRIVATE ${SDL2_LIBRARIES})
endif()
if(NOT ANDROID)
    enable_testing()
    foreach(pair "RocketModsTests;tests/mods_tests.cpp;mods" "RocketSdkServicesTests;tests/sdk_services_tests.cpp;sdk_services" "RocketSdkAudioTests;tests/sdk_audio_tests.cpp;sdk_audio" "RocketAssetLayersTests;tests/asset_layers_tests.cpp;asset_layers")
        list(GET pair 0 target)
        list(GET pair 1 source)
        list(GET pair 2 test)
        add_executable(${target} ${source})
        target_link_libraries(${target} PRIVATE RocketModsCore)
        add_test(NAME ${test} COMMAND ${target})
        set_tests_properties(${test} PROPERTIES TIMEOUT 60)
    endforeach()
    add_executable(GloverCameraModLogicTests tests/camera_mod_logic_tests.cpp)
    target_include_directories(GloverCameraModLogicTests PRIVATE "${ROCKET_SOURCE_ROOT}/modding/include")
    add_test(NAME camera_mod_logic COMMAND GloverCameraModLogicTests)
    add_executable(GloverSdkRuntimeTests tests/sdk_runtime_tests.cpp src/mods/sdk_runtime.cpp)
    target_link_libraries(GloverSdkRuntimeTests PRIVATE RocketModsCore)
    target_include_directories(GloverSdkRuntimeTests PRIVATE
        "${RUNTIME}/N64Recomp/include" "${RUNTIME}/ultramodern/include" "${RUNTIME}/librecomp/include"
        "$<TARGET_PROPERTY:ultramodern,INCLUDE_DIRECTORIES>" "$<TARGET_PROPERTY:librecomp,INCLUDE_DIRECTORIES>")
    add_test(NAME sdk_runtime COMMAND GloverSdkRuntimeTests)
    find_package(Threads REQUIRED)
    add_executable(GloverNativeContractTests tests/glover_native_contract_tests.cpp src/glover_boot_probe.cpp
        src/glover_graphics.cpp src/graphics_enhancements.cpp)
    target_link_libraries(GloverNativeContractTests PRIVATE Threads::Threads)
    target_include_directories(GloverNativeContractTests PRIVATE
        "${ROCKET_SOURCE_ROOT}/src" "${RUNTIME}/N64Recomp/include"
        "${ROCKET_SOURCE_ROOT}/extern/rt64/src"
        "${ROCKET_SOURCE_ROOT}/extern/rt64/src/contrib/hlslpp/include")
    add_test(NAME glover_native_contract COMMAND GloverNativeContractTests)
    set(GLOVER_IMGUI "${RT64_ROOT}/src/contrib/imgui")
    add_executable(GloverLauncherDesignTests tests/glover_launcher_design_tests.cpp
        "${GLOVER_IMGUI}/imgui.cpp" "${GLOVER_IMGUI}/imgui_draw.cpp"
        "${GLOVER_IMGUI}/imgui_tables.cpp" "${GLOVER_IMGUI}/imgui_widgets.cpp")
    target_include_directories(GloverLauncherDesignTests PRIVATE "${ROCKET_SOURCE_ROOT}/src" "${RT64_ROOT}/src/contrib")
    target_compile_definitions(GloverLauncherDesignTests PRIVATE
        GLOVER_LAUNCHER_FONT_ROOT="${ROCKET_SOURCE_ROOT}/src/UI/fonts")
    add_test(NAME launcher_design COMMAND GloverLauncherDesignTests)
    add_executable(RocketRuntimeLogTests tests/runtime_log_tests.cpp src/runtime_log.cpp)
    target_include_directories(RocketRuntimeLogTests PRIVATE "${ROCKET_SOURCE_ROOT}/src")
    target_link_libraries(RocketRuntimeLogTests PRIVATE Threads::Threads)
    if(WIN32)
        set_target_properties(RocketRuntimeLogTests PROPERTIES WIN32_EXECUTABLE TRUE)
        target_link_options(RocketRuntimeLogTests PRIVATE /ENTRY:mainCRTStartup)
    endif()
    add_test(NAME runtime_log COMMAND RocketRuntimeLogTests)
    add_executable(RocketControlsTests tests/controls_tests.cpp src/runtime_input.cpp src/binding_capture.cpp)
    target_include_directories(RocketControlsTests PRIVATE "${ROCKET_SOURCE_ROOT}/src")
    if(WIN32)
        target_include_directories(RocketControlsTests PRIVATE "${SDLBASE}/include")
        target_link_directories(RocketControlsTests PRIVATE "${SDLBASE}/lib/x64")
        target_link_libraries(RocketControlsTests PRIVATE SDL2)
        add_custom_command(TARGET RocketControlsTests POST_BUILD COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${SDLBASE}/lib/x64/SDL2.dll" "$<TARGET_FILE_DIR:RocketControlsTests>/SDL2.dll")
    else()
        target_include_directories(RocketControlsTests PRIVATE ${SDL2_INCLUDE_DIRS})
        target_link_libraries(RocketControlsTests PRIVATE ${SDL2_LIBRARIES})
    endif()
    add_test(NAME controls COMMAND RocketControlsTests)
    set_tests_properties(glover_native_contract runtime_log controls PROPERTIES TIMEOUT 60)
endif()

# The inherited UI loader looks beside the executable on desktop.
if(NOT ANDROID)
    add_custom_command(TARGET RocketR POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E make_directory "$<TARGET_FILE_DIR:RocketR>/assets/ui"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${ROCKET_SOURCE_ROOT}/src/UI/Glover-R-green-full-resolution.png"
            "$<TARGET_FILE_DIR:RocketR>/assets/ui/Glover-R-green-full-resolution.png"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${ROCKET_SOURCE_ROOT}/src/UI/Glover-R-green-512x512.png"
            "$<TARGET_FILE_DIR:RocketR>/assets/ui/Glover-R-green-512x512.png"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "$<TARGET_FILE_DIR:RocketR>/assets/ui/fonts"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${ROCKET_SOURCE_ROOT}/src/UI/fonts/Bungee-Regular.ttf"
            "$<TARGET_FILE_DIR:RocketR>/assets/ui/fonts/Bungee-Regular.ttf"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${ROCKET_SOURCE_ROOT}/src/UI/fonts/OFL.txt"
            "$<TARGET_FILE_DIR:RocketR>/assets/ui/fonts/OFL.txt"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${ROCKET_SOURCE_ROOT}/src/UI/fonts/Selawik-Regular.ttf"
            "$<TARGET_FILE_DIR:RocketR>/assets/ui/fonts/Selawik-Regular.ttf"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${ROCKET_SOURCE_ROOT}/src/UI/fonts/Selawik-Semibold.ttf"
            "$<TARGET_FILE_DIR:RocketR>/assets/ui/fonts/Selawik-Semibold.ttf"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${ROCKET_SOURCE_ROOT}/src/UI/fonts/Selawik-OFL.txt"
            "$<TARGET_FILE_DIR:RocketR>/assets/ui/fonts/Selawik-OFL.txt"
        VERBATIM)
endif()
