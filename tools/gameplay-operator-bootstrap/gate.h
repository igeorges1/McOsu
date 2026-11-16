#ifndef MCOSU_GAMEPLAY_OPERATOR_BOOTSTRAP_GATE_H
#define MCOSU_GAMEPLAY_OPERATOR_BOOTSTRAP_GATE_H

#include <algorithm>
#include <string_view>
#include "runtime_policy.h"

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
    int manifest_version = 1;
};

struct RuntimeObservation
{
    std::string_view runtime_id;
    std::string_view version;
    int machine;
    int subsystem;
    std::string_view image;
    std::string_view entry;
    std::array<std::string_view, runtime_policy::flags.size()> flags;
    std::string_view path_file;
    Object paths;
    std::string_view path_bytes;
    bool pre_interpreter;
    bool redirected_stdio;
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
inline bool ready(std::string_view approved_manifest, const Observation &observed)
{
    return valid_digest(approved_manifest) && observed.manifest_sha256 == approved_manifest
        && observed.ancestors_proved && observed.exact_members && observed.closed_imports && observed.closed_dlls
        && protected_object(observed.root) && protected_object(observed.manifest)
        && protected_object(observed.python) && protected_object(observed.script);
}

template <typename Load>
bool enter_supervisor(std::string_view approved_manifest, const Observation &observed, Load &&load)
{
    return observed.manifest_version == 1 && ready(approved_manifest, observed)
        && load(interpreter, entry);
}

template <typename Load>
bool enter_supervisor(std::string_view approved_manifest, const Observation &observed,
                      const RuntimeObservation &runtime, Load &&load)
{
    return observed.manifest_version == runtime_policy::manifest_version
        && ready(approved_manifest, observed)
        && runtime.runtime_id == runtime_policy::runtime_id && runtime.version == runtime_policy::version
        && runtime.machine == runtime_policy::machine && runtime.subsystem == runtime_policy::subsystem
        && runtime.image == runtime_policy::image && runtime.entry == runtime_policy::entry
        && runtime.flags == runtime_policy::flags && runtime.path_file == runtime_policy::path_file
        && protected_object(runtime.paths) && runtime.path_bytes == runtime_policy::paths
        && runtime.pre_interpreter && runtime.redirected_stdio
        && load(runtime_policy::image, runtime_policy::entry, runtime_policy::flags);
}
}

#endif
