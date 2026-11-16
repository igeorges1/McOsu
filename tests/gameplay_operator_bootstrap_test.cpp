#include "../tools/gameplay-operator-bootstrap/gate.h"
#include <cstdio>
#include <string_view>
#include "verification/ConsoleCheckAssertions.h"

int main()
{
    using namespace capture_bootstrap;
    constexpr std::string_view pin = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    const Object root{"root-id", "root-id", true, false, false};
    const Object manifest{"manifest-id", "manifest-id", true, false, false};
    const Object python{"python-id", "python-id", true, false, false};
    const Object script{"script-id", "script-id", true, false, false};
    const Observation expected{pin, root, manifest, python, script, true, true, true, true};
    int calls = 0;
    const auto inert_load = [&calls](std::string_view image, std::string_view role)
    {
        assert(image == "python/python.exe");
        assert(role == "tools/operator_supervisor.py");
        ++calls;
        return true;
    };
    assert(!enter_supervisor("invalid", expected, inert_load));
    Observation invalid = expected;
    invalid.root.ordinary_write = true;
    assert(!enter_supervisor(pin, invalid, inert_load));
    invalid = expected;
    invalid.manifest.current = "other-object";
    assert(!enter_supervisor(pin, invalid, inert_load));
    invalid = expected;
    invalid.python.redirected = true;
    assert(!enter_supervisor(pin, invalid, inert_load));
    invalid = expected;
    invalid.script.protected_owner = false;
    assert(!enter_supervisor(pin, invalid, inert_load));
    invalid = expected;
    invalid.exact_members = false;
    assert(!enter_supervisor(pin, invalid, inert_load));
    invalid = expected;
    invalid.closed_imports = false;
    assert(!enter_supervisor(pin, invalid, inert_load));
    invalid = expected;
    invalid.closed_dlls = false;
    assert(!enter_supervisor(pin, invalid, inert_load));
    assert(calls == 0);
    assert(enter_supervisor(pin, expected, inert_load));
    assert(calls == 1);
    Observation selected = expected;
    selected.manifest_version = 2;
    const Object paths{"paths-id", "paths-id", true, false, false};
    const RuntimeObservation gui{"cpython-3.14.10-amd64-embed", "3.14.10", 0x8664, 2,
        "python/pythonw.exe", "tools/operator_supervisor.py", {"-I", "-B", "-S"},
        "python/python314._pth", paths, "python314.zip\n.\n../tools\n../route\n", true, true};
    const auto gui_load = [&calls](std::string_view image, std::string_view role, const auto &flags)
    {
        assert(image == "python/pythonw.exe");
        assert(role == "tools/operator_supervisor.py");
        assert(flags == (std::array<std::string_view, 3>{"-I", "-B", "-S"}));
        ++calls;
        return true;
    };
    assert(!enter_supervisor(pin, selected, inert_load));
    assert(!enter_supervisor(pin, expected, gui, gui_load));
    const auto rejects = [&](const auto &change)
    {
        auto candidate = gui;
        change(candidate);
        assert(!enter_supervisor(pin, selected, candidate, gui_load));
    };
    rejects([](auto &candidate) { candidate.runtime_id = "other"; });
    rejects([](auto &candidate) { candidate.version = "3.14.9"; });
    rejects([](auto &candidate) { candidate.machine = 0x014c; });
    rejects([](auto &candidate) { candidate.subsystem = 3; });
    rejects([](auto &candidate) { candidate.image = "python/python.exe"; });
    rejects([](auto &candidate) { candidate.entry = "tools/operator_watchdog.py"; });
    rejects([](auto &candidate) { candidate.flags[2] = "-i"; });
    rejects([](auto &candidate) { candidate.path_file = "python/pythonw._pth"; });
    rejects([](auto &candidate) { candidate.paths.current = "other-object"; });
    rejects([](auto &candidate) { candidate.path_bytes = "python314.zip\n.\nimport site\n"; });
    rejects([](auto &candidate) { candidate.pre_interpreter = false; });
    rejects([](auto &candidate) { candidate.redirected_stdio = false; });
    assert(calls == 1);
    assert(enter_supervisor(pin, selected, gui, gui_load));
    assert(calls == 2);
    std::puts("COMPLETE gameplay operator native bootstrap predicates cases=24");
}
