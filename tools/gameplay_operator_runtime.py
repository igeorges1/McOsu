"""Selected operator runtime policy and its generated projections."""

RUNTIME_ID = "cpython-3.14.10-amd64-embed"
VERSION = "3.14.10"
MANIFEST_VERSION = 2
MACHINE = 0x8664
CONSOLE = "python/python.exe"
BACKGROUND = "python/pythonw.exe"
CONSOLE_SUBSYSTEM, BACKGROUND_SUBSYSTEM = 3, 2
PATH_FILE = "python/python314._pth"
STDLIB = "python/python314.zip"
RUNTIME_DLL = "python/python314.dll"
PATHS = b"python314.zip\n.\n../tools\n../route\n"
FLAGS = ("-I", "-B", "-S")
POLICY_SOURCE = "tools/gameplay_operator_runtime.py"
MARK_INVENTORY = "tools/gameplay_mark_inventory.py"
OPERATOR = "tools/gameplay_operator.py"
PACKAGE = "tools/gameplay_operator_package.py"

REQUIRED_EDGES = {
    CONSOLE: {RUNTIME_DLL, STDLIB, PATH_FILE},
    BACKGROUND: {RUNTIME_DLL, STDLIB, PATH_FILE},
    RUNTIME_DLL: {"python/vcruntime140.dll"},
    "python/_ctypes.pyd": {"python/libffi-8.dll"},
    OPERATOR: {MARK_INVENTORY, PACKAGE},
    PACKAGE: {POLICY_SOURCE},
}
REQUIRED_RESOLUTIONS = {
    (CONSOLE, "dll", "python314.dll", RUNTIME_DLL),
    (BACKGROUND, "dll", "python314.dll", RUNTIME_DLL),
    (OPERATOR, "import", "gameplay_mark_inventory", MARK_INVENTORY),
    (OPERATOR, "import", "gameplay_operator_package", PACKAGE),
    (PACKAGE, "import", "gameplay_operator_runtime", POLICY_SOURCE),
}

# Entry roles record their execution context and fixed interpreter.
ENTRIES = (
    ("operator", OPERATOR, CONSOLE, "Visible normal console"),
    ("supervisor", "tools/operator_supervisor.py", BACKGROUND, "Elevated supervisor"),
    ("controller", "tools/operator_controller.py", BACKGROUND, "Elevated controller"),
    ("watchdog", "tools/operator_watchdog.py", BACKGROUND, "Elevated watchdog"),
    ("cue_worker", "tools/operator_cue_worker.py", BACKGROUND, "Normal background cue worker"),
)

# Integrity pins from the existing vendor stage. The project supplies PATH_FILE.
RUNTIME_FILES = {
    "python/_ctypes.pyd": (143072, "adf71d85781a2fe937fcc44c0961498e2cf30849f9863ff7b5f7510817cea952"),
    "python/_overlapped.pyd": (58080, "8f35ff35e76a2308ce0a50200fb01b55569f30952098239f7e000f3da1393a61"),
    "python/_queue.pyd": (36576, "51a3d8e40b061db4fc77f9a3b18e6c2f912c4edf467e46c95ac325d35f2be4df"),
    "python/_socket.pyd": (87776, "11f2ace2a37e59bf0f2fcfcc2523307408fa2e7f0aec561bc7531a8db130a83c"),
    "python/_uuid.pyd": (28384, "ad949327a9730feefc7f2c14db9b1b43f4351df1aad3688dc1e68e4a23f7e81c"),
    "python/libffi-8.dll": (39696, "eff52743773eb550fcc6ce3efc37c85724502233b6b002a35496d828bd7b280a"),
    "python/python.exe": (106208, "d718435b892db4ad5b547d12fec61be7baa7faf7a58d857ea58053be24c7a000"),
    "python/python314._pth": (34, "7022e7c5df5c16284d6b171af55997efcefc8c1ff21ee97bd83744234a6b3fd0"),
    "python/python314.dll": (6816992, "d8a06cc6ca3348925ea29e343e1c5c5895fe0bb433ff913e1cee44caf358aa6a"),
    "python/python314.zip": (4158438, "4e97b321fe7f470c5a2cda0414f2b9caa896835edadf03eef251a0ebc3c24cc3"),
    "python/pythonw.exe": (104672, "36392dade900489423a15686340bf5f95a64d661d9322bb4c0e0f1d4e6a84cb7"),
    "python/select.pyd": (33504, "0da869c017fd3231cfc1c1e4c4bef1bb7bf5cba38236e6d7bf1630c3507c5a1d"),
    "python/vcruntime140.dll": (178616, "d1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7"),
    "python/winsound.pyd": (32992, "df409ab34d986e3379b55a42f88e3879f903be7dc952cf8c066f704b69511723"),
}


NOTICE_DIRECTORY = "tools/gameplay-operator-notices"
UPSTREAM_NOTICE = "route/licenses/cpython-upstream-license.txt"
INCORPORATED_NOTICE = "route/licenses/cpython-incorporated-licenses.txt"
SUPPLEMENTAL_NOTICE = "route/licenses/supplemental-notices.txt"
CHANGES_NOTICE = "route/licenses/runtime-changes.txt"
NOTICE_FILES = {
    UPSTREAM_NOTICE: (35407, "935cf13e19f8c31b497d20b05d73623431a226b230c3599bc30fa3348979bc68"),
    INCORPORATED_NOTICE: (60039, "8a7329b25131f64b2bea284155f0824876b1af9f4a2f970e6335751d97dfa6dd"),
    SUPPLEMENTAL_NOTICE: (15827, "9aa10838e74ee68fbf0618e683ac6c28e22681f518aff008601f58a704cf9e27"),
    CHANGES_NOTICE: (1982, "803ff8ea87efb249dcf099ad0b3c22d41a82a5d6067dc486d16ba5735c89fec8"),
}
NOTICE_SOURCE_FILES = {
    f"{NOTICE_DIRECTORY}/{path.rsplit('/', 1)[1]}": pin for path, pin in NOTICE_FILES.items()
}

CORE_LICENSE = "cpython-embed-core"
SUPPLEMENTED_LICENSE = "cpython-embed-supplemented"
CHANGES_LICENSE = "cpython-embed-entry-policy"
CORE_NOTICES = (UPSTREAM_NOTICE, INCORPORATED_NOTICE)
LICENSE_NOTICES = {
    CORE_LICENSE: CORE_NOTICES,
    SUPPLEMENTED_LICENSE: (*CORE_NOTICES, SUPPLEMENTAL_NOTICE),
    CHANGES_LICENSE: (*CORE_NOTICES, CHANGES_NOTICE),
    "cpython-incorporated-text": (INCORPORATED_NOTICE,),
    "cpython-supplemental-text": (SUPPLEMENTAL_NOTICE,),
    "cpython-runtime-changes-text": (CHANGES_NOTICE,),
}
MEMBER_LICENSES = {
    **dict.fromkeys(RUNTIME_FILES, CORE_LICENSE),
    **dict.fromkeys((RUNTIME_DLL, STDLIB, "python/_ctypes.pyd", "python/libffi-8.dll"), SUPPLEMENTED_LICENSE),
    **dict.fromkeys((CONSOLE, BACKGROUND, PATH_FILE), CHANGES_LICENSE),
    UPSTREAM_NOTICE: CORE_LICENSE,
    INCORPORATED_NOTICE: "cpython-incorporated-text",
    SUPPLEMENTAL_NOTICE: "cpython-supplemental-text",
    CHANGES_NOTICE: "cpython-runtime-changes-text",
}


def reference_lines():
    lines = [
        "### Proposed protected operator runtime", "",
        f"The draft selects CPython {VERSION} AMD64 Windows embeddable "
        f"(`{RUNTIME_ID}`) for package manifest version {MANIFEST_VERSION}.",
        "Each entry uses " + " ".join(f"`{flag}`" for flag in FLAGS) + " before the fixed script.",
        f"`{PATH_FILE}` contains these lines in order and ends with a newline.",
        "", *[f"- `{line.decode('ascii')}`" for line in PATHS.splitlines()],
        "", "| Context | Entry | Runtime image |", "| --- | --- | --- |",
    ]
    lines.extend(f"| {context} | `{entry}` | `{image}` |" for _, entry, image, context in ENTRIES)
    lines += [
        "", "The version 2 package pins these notice files and binds each runtime member to its notice group.",
        "", *[f"- `{path}`" for path in NOTICE_FILES],
        "", "The reviewed notice set covers selected runtime evidence. Redistribution applicability, "
        "signer trust and native loader qualification remain separate.",
    ]
    return lines


def native_policy_header():
    flags = ", ".join(f'"{flag}"' for flag in FLAGS)
    paths = PATHS.decode("ascii").replace("\n", r"\n")
    supervisor = next(entry for role, entry, _, _ in ENTRIES if role == "supervisor")
    return f"""// Generated by tests/check-timing-audio-settings.py.
#ifndef MCOSU_GAMEPLAY_OPERATOR_RUNTIME_POLICY_H
#define MCOSU_GAMEPLAY_OPERATOR_RUNTIME_POLICY_H

#include <array>
#include <string_view>

namespace capture_bootstrap::runtime_policy
{{
inline constexpr int manifest_version = {MANIFEST_VERSION};
inline constexpr std::string_view runtime_id = "{RUNTIME_ID}";
inline constexpr std::string_view version = "{VERSION}";
inline constexpr int machine = 0x{MACHINE:04x};
inline constexpr int subsystem = {BACKGROUND_SUBSYSTEM};
inline constexpr std::string_view image = "{BACKGROUND}";
inline constexpr std::string_view entry = "{supervisor}";
inline constexpr std::string_view path_file = "{PATH_FILE}";
inline constexpr std::string_view paths = "{paths}";
inline constexpr std::array<std::string_view, {len(FLAGS)}> flags{{{flags}}};
}}

#endif
"""
