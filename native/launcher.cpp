#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>

#include <string>

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    wchar_t module_path[32768]{};
    const DWORD length = GetModuleFileNameW(nullptr, module_path, 32768);
    if (length == 0 || length >= 32768) {
        MessageBoxW(nullptr, L"无法确定启动器位置。", L"EU4 联机存档助手", MB_ICONERROR);
        return 1;
    }
    std::wstring root(module_path, length);
    const auto separator = root.find_last_of(L"\\/");
    if (separator == std::wstring::npos) {
        return 1;
    }
    root.resize(separator);
    const std::wstring work_dir = root + L"\\release\\EU4_AutoSave_Assistant";
    const std::wstring target = work_dir + L"\\EU4_AutoSave_Assistant.exe";

    SHELLEXECUTEINFOW launch{};
    launch.cbSize = sizeof(launch);
    launch.fMask = SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI;
    launch.lpVerb = L"open";
    launch.lpFile = target.c_str();
    launch.lpDirectory = work_dir.c_str();
    launch.nShow = SW_SHOWNORMAL;
    if (!ShellExecuteExW(&launch)) {
        const std::wstring message =
            L"无法启动主程序：\n" + target +
            L"\n\n请先运行 scripts\\package.ps1 重新生成发布文件。";
        MessageBoxW(nullptr, message.c_str(), L"EU4 联机存档助手", MB_ICONERROR);
        return 2;
    }
    return 0;
}
