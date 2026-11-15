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
    std::puts("COMPLETE gameplay operator native bootstrap predicates cases=9");
}
