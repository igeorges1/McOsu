#ifndef MCOSU_GAMEPLAY_OPERATOR_BOOTSTRAP_GATE_H
#define MCOSU_GAMEPLAY_OPERATOR_BOOTSTRAP_GATE_H

#include <algorithm>
#include <string_view>

namespace capture_bootstrap
{
inline constexpr std::string_view interpreter = "python/python.exe";
inline constexpr std::string_view entry = "tools/operator_supervisor.py";

struct Object
{
    std::string_view first;
    std::string_view current;
    bool protected_owner;
    bool ordinary_write;
    bool redirected;
};

struct Observation
{
    std::string_view manifest_sha256;
    Object root;
    Object manifest;
    Object python;
    Object script;
    bool ancestors_proved;
    bool exact_members;
    bool closed_imports;
    bool closed_dlls;
};

inline bool protected_object(const Object &object)
{
    return !object.first.empty() && object.first == object.current
        && object.protected_owner && !object.ordinary_write && !object.redirected;
}

inline bool valid_digest(std::string_view hash)
{
    return hash.size() == 64 && std::all_of(hash.begin(), hash.end(), [](char value)
    {
        return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
    });
}

// The adapter must obtain the observations before interpreter/module entry.
// A successful return from load is only dispatch, not consent or capture.
template <typename Load>
bool enter_supervisor(std::string_view approved_manifest, const Observation &observed, Load &&load)
{
    if (!valid_digest(approved_manifest) || observed.manifest_sha256 != approved_manifest
        || !observed.ancestors_proved || !observed.exact_members || !observed.closed_imports || !observed.closed_dlls
        || !protected_object(observed.root) || !protected_object(observed.manifest)
        || !protected_object(observed.python) || !protected_object(observed.script))
        return false;

    return load(interpreter, entry);
}
}

#endif
