cmake_minimum_required(VERSION 3.20)
project(EU4AutoSaveBridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_compile_definitions(UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)

add_library(EU4AutoSaveBridge SHARED bridge.cpp)
target_link_libraries(EU4AutoSaveBridge PRIVATE user32)
set_target_properties(EU4AutoSaveBridge PROPERTIES PREFIX "")

add_executable(EU4BridgeInjector injector.cpp)
target_link_libraries(EU4BridgeInjector PRIVATE user32)

add_executable(EU4BridgeHarness WIN32 bridge_harness.cpp)
target_link_libraries(EU4BridgeHarness PRIVATE shell32 user32 kernel32)

add_executable(EU4AutoSaveLauncher WIN32 launcher.cpp)
target_link_libraries(EU4AutoSaveLauncher PRIVATE shell32 user32 kernel32)
