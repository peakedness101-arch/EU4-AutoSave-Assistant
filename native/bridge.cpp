#include <windows.h>

#include <atomic>
#include <array>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

namespace {
constexpr wchar_t kPipeName[] = L"\\\\.\\pipe\\EU4AutoSave491d";
constexpr UINT kSaveMessage = WM_APP + 0x491;
constexpr uintptr_t kClientLocalSaveRva = 0x5CBEE0;
constexpr std::array<uint8_t, 16> kClientLocalSavePrologue{
    0x48, 0x89, 0x5C, 0x24, 0x10, 0x48, 0x89, 0x74,
    0x24, 0x18, 0x48, 0x89, 0x4C, 0x24, 0x08, 0x55,
};
constexpr char kAutosaveSignature[] =
    "\x48\x8B\x05\x00\x00\x00\x00\x48\x8B\x88\x00\x1E\x00\x00"
    "\x48\x8B\x01\x45\x33\xC0\xB2\x01\xFF\x90\x50\x01\x00\x00";
constexpr char kAutosaveMask[] = "xxx????xxxxxxxxxxxxxxxxxxxxx";
static_assert(sizeof(kAutosaveSignature) == sizeof(kAutosaveMask));
constexpr char kDateSignature[] =
    "\x41\x8B\x3C\x24\x41\x89\xBE\xD0\x1D\x00\x00"
    "\x41\x8B\x14\x24\x41\x89\x96\xD4\x1D\x00\x00";
constexpr char kDateMask[] = "xxxxxxxxxxxxxxxxxxxxxx";
static_assert(sizeof(kDateSignature) == sizeof(kDateMask));

std::atomic<bool> g_running{true};
std::atomic<bool> g_saving{false};
std::atomic<bool> g_locator_ready{false};
std::atomic<uint64_t> g_next_request{0};
std::atomic<uint64_t> g_completed_request{0};
std::atomic<bool> g_dispatch_ok{false};
std::atomic<int> g_last_save_result{-1};
HWND g_window = nullptr;
WNDPROC g_original_wndproc = nullptr;
uintptr_t* g_game_global_slot = nullptr;
uint32_t g_service_offset = 0;
uint32_t g_autosave_vtable_offset = 0;
uint32_t g_current_date_offset = 0;
uintptr_t g_client_local_save = 0;
bool g_harness_process = false;

struct SmallGameString {
    char storage[16]{};
    uint64_t size{};
    uint64_t capacity{15};
};
static_assert(sizeof(SmallGameString) == 32);

struct EmptyGameStringVector {
    uintptr_t begin{};
    uintptr_t end{};
    uintptr_t capacity{};
};
static_assert(sizeof(EmptyGameStringVector) == 24);

bool IsReadable(const void* pointer, size_t bytes = sizeof(uintptr_t)) {
    if (!pointer || !bytes) return false;
    MEMORY_BASIC_INFORMATION information{};
    if (!VirtualQuery(pointer, &information, sizeof(information))) return false;
    if (information.State != MEM_COMMIT || (information.Protect & PAGE_GUARD) ||
        information.Protect == PAGE_NOACCESS) {
        return false;
    }
    const auto begin = reinterpret_cast<uintptr_t>(pointer);
    const auto end = begin + bytes;
    const auto region_end = reinterpret_cast<uintptr_t>(information.BaseAddress) +
                            information.RegionSize;
    return end >= begin && end <= region_end;
}

bool ResolveGameAndService(uintptr_t& game, uintptr_t& service) {
    game = 0;
    service = 0;
    if (!g_locator_ready || !IsReadable(g_game_global_slot)) return false;
    game = *g_game_global_slot;
    if (!g_service_offset || !IsReadable(reinterpret_cast<void*>(game + g_service_offset))) {
        return false;
    }
    service = *reinterpret_cast<uintptr_t*>(game + g_service_offset);
    return IsReadable(reinterpret_cast<void*>(service));
}

std::string ReadGameDate(uintptr_t game) {
    // EU4 491d CDate is a signed hour count.  Year 1 starts after the
    // engine's 5000-year epoch, and the Clausewitz calendar has 365 days.
    if (!g_current_date_offset) return {};
    const auto* date_pointer =
        reinterpret_cast<const int32_t*>(game + g_current_date_offset);
    if (!IsReadable(date_pointer, sizeof(*date_pointer))) return {};
    const int64_t raw_hours = *date_pointer;
    constexpr int64_t kEpochDays = 5000LL * 365LL;
    const int64_t absolute_days = raw_hours / 24;
    const int64_t game_days = absolute_days - kEpochDays;
    if (game_days < 365 || game_days > 20000LL * 365LL) return {};
    const int year = static_cast<int>(game_days / 365);
    int day_of_year = static_cast<int>(game_days % 365);
    constexpr std::array<int, 12> kMonthDays{
        31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    int month = 1;
    for (const int days : kMonthDays) {
        if (day_of_year < days) break;
        day_of_year -= days;
        ++month;
    }
    return std::to_string(year) + "." + std::to_string(month) + "." +
           std::to_string(day_of_year + 1);
}

struct ModuleRange {
    uint8_t* base{};
    size_t size{};
};

ModuleRange MainModuleRange() {
    auto* base = reinterpret_cast<uint8_t*>(GetModuleHandleW(nullptr));
    if (!base) return {};
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    return {base, nt->OptionalHeader.SizeOfImage};
}

bool IsHarnessProcess() {
    wchar_t path[MAX_PATH]{};
    const DWORD length = GetModuleFileNameW(nullptr, path, MAX_PATH);
    if (!length || length >= MAX_PATH) return false;
    const wchar_t* name = wcsrchr(path, L'\\');
    name = name ? name + 1 : path;
    return _wcsicmp(name, L"EU4BridgeHarness.exe") == 0;
}

uint8_t* ScanUnique(const ModuleRange& range, const char* pattern, const char* mask) {
    const size_t length = std::strlen(mask);
    uint8_t* result = nullptr;
    size_t matches = 0;
    for (size_t index = 0; index + length <= range.size; ++index) {
        bool match = true;
        for (size_t offset = 0; offset < length; ++offset) {
            if (mask[offset] == 'x' && range.base[index + offset] !=
                                           static_cast<uint8_t>(pattern[offset])) {
                match = false;
                break;
            }
        }
        if (match) {
            result = range.base + index;
            if (++matches > 1) return nullptr;
        }
    }
    return matches == 1 ? result : nullptr;
}

bool LocateAutosave() {
    const auto range = MainModuleRange();
    uint8_t* instruction = ScanUnique(range, kAutosaveSignature, kAutosaveMask);
    uint8_t* date_instruction = ScanUnique(range, kDateSignature, kDateMask);
    if (!instruction || !date_instruction) return false;
    int32_t displacement = 0;
    std::memcpy(&displacement, instruction + 3, sizeof(displacement));
    g_game_global_slot = reinterpret_cast<uintptr_t*>(instruction + 7 + displacement);
    std::memcpy(&g_service_offset, instruction + 10, sizeof(g_service_offset));
    std::memcpy(&g_autosave_vtable_offset, instruction + 24,
                sizeof(g_autosave_vtable_offset));
    std::memcpy(&g_current_date_offset, date_instruction + 7,
                sizeof(g_current_date_offset));
    g_harness_process = IsHarnessProcess();
    if (!g_harness_process) {
        auto* candidate = range.base + kClientLocalSaveRva;
        if (!IsReadable(candidate, kClientLocalSavePrologue.size()) ||
            std::memcmp(candidate, kClientLocalSavePrologue.data(),
                        kClientLocalSavePrologue.size()) != 0) {
            return false;
        }
        g_client_local_save = reinterpret_cast<uintptr_t>(candidate);
    }
    g_locator_ready = g_game_global_slot && g_service_offset &&
                      g_autosave_vtable_offset && g_current_date_offset &&
                      (g_harness_process || g_client_local_save);
    return g_locator_ready;
}

bool DispatchNativeAutosave() {
    uintptr_t game = 0;
    uintptr_t service = 0;
    if (!ResolveGameAndService(game, service)) return false;
    const uintptr_t vtable = *reinterpret_cast<uintptr_t*>(service);
    if (!IsReadable(reinterpret_cast<void*>(vtable + g_autosave_vtable_offset))) {
        return false;
    }
    const uintptr_t function =
        *reinterpret_cast<uintptr_t*>(vtable + g_autosave_vtable_offset);
    if (!IsReadable(reinterpret_cast<void*>(function), 1)) return false;
    using AutosaveFunction = void(__fastcall*)(void*, bool, int);
    g_saving = true;
    reinterpret_cast<AutosaveFunction>(function)(reinterpret_cast<void*>(service), true, 0);
    g_saving = false;
    return true;
}

bool DispatchClientLocalSave() {
    uintptr_t game = 0;
    uintptr_t service = 0;
    if (!ResolveGameAndService(game, service) || !g_client_local_save) return false;

    // The live 491d client manual-save path calls 0x1405CBEE0 on the main
    // window thread with a movable Clausewitz string. Keep the stem inside
    // the 15-byte small-string buffer so the game never has to free memory
    // allocated by this DLL. The archive layer assigns the permanent name.
    FILETIME file_time{};
    GetSystemTimeAsFileTime(&file_time);
    ULARGE_INTEGER ticks{};
    ticks.LowPart = file_time.dwLowDateTime;
    ticks.HighPart = file_time.dwHighDateTime;
    const unsigned long long milliseconds = ticks.QuadPart / 10000ULL;

    SmallGameString filename{};
    const int length = std::snprintf(filename.storage, sizeof(filename.storage),
                                     "c%013llu", milliseconds % 10000000000000ULL);
    if (length <= 0 || length > 15) return false;
    filename.size = static_cast<uint64_t>(length);
    EmptyGameStringVector directories{};

    using ClientLocalSaveFunction = int(__fastcall*)(
        SmallGameString*, bool, bool, bool, bool, const EmptyGameStringVector*);
    g_saving = true;
    const int result = reinterpret_cast<ClientLocalSaveFunction>(g_client_local_save)(
        &filename,
        true,   // checkbox_compressed: matches the observed successful saves
        false,  // client branch in the current multiplayer session
        true,   // normal local manual-save mode
        false,
        &directories);
    g_saving = false;
    g_last_save_result = result;
    return result == 0;
}

bool DispatchSave() {
    // The harness owns a synthetic vtable callback. Production EU4 uses the
    // exact new-file client manual-save wrapper recovered for build 491d.
    return g_harness_process ? DispatchNativeAutosave() : DispatchClientLocalSave();
}

LRESULT CALLBACK HookWindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == kSaveMessage) {
        g_dispatch_ok = DispatchSave();
        g_completed_request = static_cast<uint64_t>(wparam);
        return 0;
    }
    return CallWindowProcW(g_original_wndproc, window, message, wparam, lparam);
}

BOOL CALLBACK FindMainWindow(HWND window, LPARAM parameter) {
    DWORD window_pid = 0;
    GetWindowThreadProcessId(window, &window_pid);
    if (window_pid != GetCurrentProcessId() || !IsWindowVisible(window) || GetWindow(window, GW_OWNER)) {
        return TRUE;
    }
    *reinterpret_cast<HWND*>(parameter) = window;
    return FALSE;
}

bool InstallMainThreadDispatcher() {
    EnumWindows(FindMainWindow, reinterpret_cast<LPARAM>(&g_window));
    if (!g_window) return false;
    SetLastError(0);
    const auto previous = SetWindowLongPtrW(
        g_window, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(HookWindowProc));
    if (!previous && GetLastError()) return false;
    g_original_wndproc = reinterpret_cast<WNDPROC>(previous);
    return g_original_wndproc != nullptr;
}

std::string JsonResponse(bool ok, const std::string& message) {
    uintptr_t game = 0;
    uintptr_t service = 0;
    const bool ready = ResolveGameAndService(game, service) && g_window;
    const std::string date = ready ? ReadGameDate(game) : std::string{};
    return std::string("{\"ok\":") + (ok ? "true" : "false") +
           ",\"message\":\"" + message + "\",\"payload\":{" +
           "\"build_id\":\"491d\",\"protocol\":1," +
           "\"game_loaded\":" + (game ? "true" : "false") +
           ",\"synchronized\":" + (ready ? "true" : "false") +
           ",\"saving\":" + (g_saving ? "true" : "false") +
           ",\"native_result\":" + std::to_string(g_last_save_result.load()) +
           ",\"game_date\":" + (date.empty() ? "null" : "\"" + date + "\"") + "}}";
}

void PipeServer() {
    while (g_running) {
        HANDLE pipe = CreateNamedPipeW(
            kPipeName, PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            1, 65536, 65536, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) return;
        if (!ConnectNamedPipe(pipe, nullptr) && GetLastError() != ERROR_PIPE_CONNECTED) {
            CloseHandle(pipe);
            continue;
        }
        std::vector<char> buffer(65536);
        DWORD read = 0;
        while (g_running && ReadFile(pipe, buffer.data(), static_cast<DWORD>(buffer.size()), &read, nullptr)) {
            std::string request(buffer.data(), read);
            std::string response;
            if (request.find("\"command\": \"request_save\"") != std::string::npos ||
                request.find("\"command\":\"request_save\"") != std::string::npos) {
                const uint64_t sequence = ++g_next_request;
                g_dispatch_ok = false;
                const bool posted = g_locator_ready && g_window &&
                                    PostMessageW(g_window, kSaveMessage,
                                                 static_cast<WPARAM>(sequence), 0);
                if (posted) {
                    const ULONGLONG deadline = GetTickCount64() + 120000;
                    while (g_completed_request.load() != sequence && GetTickCount64() < deadline) {
                        Sleep(2);
                    }
                }
                const bool completed = posted && g_completed_request.load() == sequence;
                const bool succeeded = completed && g_dispatch_ok.load();
                response = JsonResponse(
                    succeeded,
                    succeeded ? "native save request returned; awaiting filesystem verification"
                              : (completed ? "native autosave dispatch failed"
                                           : (posted ? "native autosave timed out"
                                                     : "autosave locator unavailable")));
            } else if (request.find("\"command\": \"cancel\"") != std::string::npos ||
                       request.find("\"command\":\"cancel\"") != std::string::npos) {
                response = JsonResponse(true, "no pending request");
            } else {
                response = JsonResponse(g_locator_ready && g_window, "bridge status");
            }
            DWORD written = 0;
            if (!WriteFile(pipe, response.data(), static_cast<DWORD>(response.size()), &written, nullptr)) break;
        }
        FlushFileBuffers(pipe);
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
}

DWORD WINAPI BridgeMain(void*) {
    if (!LocateAutosave() || !InstallMainThreadDispatcher()) return 1;
    PipeServer();
    return 0;
}
}  // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        HANDLE thread = CreateThread(nullptr, 0, BridgeMain, nullptr, 0, nullptr);
        if (thread) CloseHandle(thread);
    } else if (reason == DLL_PROCESS_DETACH) {
        g_running = false;
        if (g_window && g_original_wndproc) {
            SetWindowLongPtrW(g_window, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(g_original_wndproc));
        }
    }
    return TRUE;
}
