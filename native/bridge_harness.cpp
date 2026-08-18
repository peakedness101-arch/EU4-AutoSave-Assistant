#include <windows.h>
#include <shellapi.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <string>
#include <vector>

namespace {
constexpr size_t kServiceOffset = 0x1E00;
constexpr size_t kDateOffset = 0x1DD0;
constexpr size_t kAutosaveVtableOffset = 0x150;

// The production bridge scans the executable image, so the harness keeps the
// 491d anchors in writable image data and patches only the RIP displacement.
alignas(16) volatile unsigned char g_autosave_anchor[] = {
    0x48, 0x8B, 0x05, 0,    0,    0,    0,    0x48, 0x8B,
    0x88, 0x00, 0x1E, 0x00, 0x00, 0x48, 0x8B, 0x01, 0x45,
    0x33, 0xC0, 0xB2, 0x01, 0xFF, 0x90, 0x50, 0x01, 0x00, 0x00,
};
alignas(16) volatile unsigned char g_date_anchor[] = {
    0x41, 0x8B, 0x3C, 0x24, 0x41, 0x89, 0xBE, 0xD0, 0x1D, 0x00, 0x00,
    0x41, 0x8B, 0x14, 0x24, 0x41, 0x89, 0x96, 0xD4, 0x1D, 0x00, 0x00,
};

std::vector<unsigned char> g_game(0x2400);
std::array<uintptr_t, (kAutosaveVtableOffset / sizeof(uintptr_t)) + 1> g_vtable{};
struct FakeService {
    uintptr_t* vtable{};
} g_service;
uintptr_t g_game_global_slot = 0;
DWORD g_main_thread_id = 0;
std::filesystem::path g_result_path;

bool WriteText(const std::filesystem::path& path, const std::string& text) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                              CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    const BOOL ok = WriteFile(file, text.data(), static_cast<DWORD>(text.size()),
                              &written, nullptr);
    FlushFileBuffers(file);
    CloseHandle(file);
    return ok && written == text.size();
}

extern "C" void FakeAutosave(void*, bool automatic, int kind) {
    const DWORD callback_thread_id = GetCurrentThreadId();
    const std::string json =
        std::string("{\"main_thread_id\":") + std::to_string(g_main_thread_id) +
        ",\"callback_thread_id\":" + std::to_string(callback_thread_id) +
        ",\"automatic\":" + (automatic ? "true" : "false") +
        ",\"kind\":" + std::to_string(kind) + "}";
    WriteText(g_result_path, json);
}

int32_t EncodeDate(int year, int month, int day) {
    constexpr std::array<int, 12> kMonthDays{
        31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    int day_of_year = day - 1;
    for (int index = 0; index < month - 1; ++index) day_of_year += kMonthDays[index];
    const int64_t days = static_cast<int64_t>(year + 5000) * 365 + day_of_year;
    return static_cast<int32_t>(days * 24);
}

bool PrepareFakeGame() {
    // Volatile reads keep the profile anchor in the final PE image.
    if (g_date_anchor[0] != 0x41 || g_date_anchor[sizeof(g_date_anchor) - 1] != 0x00) {
        return false;
    }
    g_game_global_slot = reinterpret_cast<uintptr_t>(g_game.data());
    const intptr_t displacement =
        reinterpret_cast<intptr_t>(&g_game_global_slot) -
        (reinterpret_cast<intptr_t>(g_autosave_anchor) + 7);
    if (displacement < INT32_MIN || displacement > INT32_MAX) return false;
    const int32_t relative = static_cast<int32_t>(displacement);
    std::memcpy(const_cast<unsigned char*>(g_autosave_anchor) + 3, &relative,
                sizeof(relative));

    g_vtable[kAutosaveVtableOffset / sizeof(uintptr_t)] =
        reinterpret_cast<uintptr_t>(&FakeAutosave);
    g_service.vtable = g_vtable.data();
    const uintptr_t service = reinterpret_cast<uintptr_t>(&g_service);
    std::memcpy(g_game.data() + kServiceOffset, &service, sizeof(service));
    const int32_t date = EncodeDate(1767, 7, 27);
    std::memcpy(g_game.data() + kDateOffset, &date, sizeof(date));
    return true;
}
}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, wchar_t*, int) {
    int argc = 0;
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv || argc != 3) return 2;
    const std::filesystem::path ready_path = std::filesystem::absolute(argv[1]);
    g_result_path = std::filesystem::absolute(argv[2]);
    LocalFree(argv);
    if (!PrepareFakeGame()) return 3;

    g_main_thread_id = GetCurrentThreadId();
    HWND window = CreateWindowExW(0, L"STATIC", L"EU4 491d Bridge Harness",
                                  WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
                                  640, 360, nullptr, nullptr, instance, nullptr);
    if (!window) return 4;
    ShowWindow(window, SW_SHOWNOACTIVATE);
    UpdateWindow(window);
    if (!WriteText(ready_path,
                   std::string("{\"pid\":") + std::to_string(GetCurrentProcessId()) +
                       ",\"main_thread_id\":" + std::to_string(g_main_thread_id) + "}")) {
        return 5;
    }

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return 0;
}
