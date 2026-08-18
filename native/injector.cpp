#include <windows.h>

#include <filesystem>
#include <iostream>
#include <string>

namespace {
constexpr DWORD kAccess = PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                          PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ;

std::wstring ErrorText(DWORD error) {
    wchar_t* buffer = nullptr;
    FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                       FORMAT_MESSAGE_IGNORE_INSERTS,
                   nullptr, error, 0, reinterpret_cast<wchar_t*>(&buffer), 0, nullptr);
    std::wstring result = buffer ? buffer : L"Unknown error";
    if (buffer) LocalFree(buffer);
    return result;
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc != 3) {
        std::wcerr << L"Usage: EU4BridgeInjector.exe <pid> <absolute-dll-path>\n";
        return 2;
    }
    const DWORD pid = std::wcstoul(argv[1], nullptr, 10);
    const std::filesystem::path dll_path = std::filesystem::absolute(argv[2]);
    if (!std::filesystem::is_regular_file(dll_path)) {
        std::wcerr << L"DLL not found: " << dll_path << L"\n";
        return 3;
    }
    HANDLE process = OpenProcess(kAccess, FALSE, pid);
    if (!process) {
        std::wcerr << L"OpenProcess failed: " << ErrorText(GetLastError()) << L"\n";
        return 4;
    }
    const std::wstring path = dll_path.wstring();
    const SIZE_T bytes = (path.size() + 1) * sizeof(wchar_t);
    void* remote = VirtualAllocEx(process, nullptr, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote || !WriteProcessMemory(process, remote, path.c_str(), bytes, nullptr)) {
        std::wcerr << L"Writing DLL path failed: " << ErrorText(GetLastError()) << L"\n";
        if (remote) VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        CloseHandle(process);
        return 5;
    }
    auto load_library = reinterpret_cast<LPTHREAD_START_ROUTINE>(
        GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW"));
    HANDLE thread = CreateRemoteThread(process, nullptr, 0, load_library, remote, 0, nullptr);
    if (!thread) {
        std::wcerr << L"CreateRemoteThread failed: " << ErrorText(GetLastError()) << L"\n";
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        CloseHandle(process);
        return 6;
    }
    WaitForSingleObject(thread, 10000);
    DWORD module_handle = 0;
    GetExitCodeThread(thread, &module_handle);
    CloseHandle(thread);
    VirtualFreeEx(process, remote, 0, MEM_RELEASE);
    CloseHandle(process);
    if (!module_handle) {
        std::wcerr << L"LoadLibraryW returned null.\n";
        return 7;
    }
    std::wcout << L"EU4AutoSaveBridge loaded into PID " << pid << L".\n";
    return 0;
}

