// Offline classic ETW scheduler evidence for a verified capture. No logger controls.
#include <windows.h>
#include <evntrace.h>
#include <tdh.h>
#include <array>
#include <climits>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cstddef>
#include <string_view>
#include <cerrno>
#include <vector>

namespace {
constexpr GUID processGuid{0x3d6fa8d0,0xfe05,0x11d0,{0x9d,0xda,0,0xc0,0x4f,0xd7,0xba,0x7c}};
constexpr GUID threadGuid{0x3d6fa8d1,0xfe05,0x11d0,{0x9d,0xda,0,0xc0,0x4f,0xd7,0xba,0x7c}};
constexpr size_t maxEvents = 131072;

struct Request {
    unsigned pid, tid;
    long long qpf, active, followingPoll, lower, upper;
    size_t events;
};
struct Life { long long tick; unsigned kind; unsigned long long key; };
struct Event { long long tick; char kind; unsigned cpu, detail; };
enum Reject { Unreadable, Version, Length, SelfSwitch, NamedSchema, NamedRead, NamedMismatch };
struct Shape {
    unsigned opcode, version, length, flags;
    Reject reason;
    size_t count;
    ULONG firstStatus = ULONG_MAX, firstBytes = 0;
    ULONG secondStatus = ULONG_MAX, secondBytes = 0;
    ULONG detailStatus = ULONG_MAX, detailBytes = 0;
};
struct Result {
    std::array<Life, 8> processes{}, threads{};
    explicit Result(Request input) : request(input), events(input.events) {}
    Request request;
    std::vector<Event> events;
    size_t np = 0, nt = 0, size = 0;
    bool invalidLife = false, invalidSchedule = false, overflow = false;
    std::array<Shape, 16> shapes{};
    size_t shapeCount = 0, rejected = 0;
    size_t boundaryRecords = 0;
    size_t v4Candidates = 0, v4Checked = 0, v4Schema = 0, v4Corroborated = 0, v4Accepted = 0;
    bool shapeOverflow = false;
};

struct Tdh {
    decltype(&TdhGetEventInformation) info = TdhGetEventInformation;
    decltype(&TdhGetPropertySize) size = TdhGetPropertySize;
    decltype(&TdhGetProperty) read = TdhGetProperty;
};

void inspectSize(EVENT_RECORD& event, const wchar_t* name, ULONG& status, ULONG& bytes, const Tdh& tdh) {
    PROPERTY_DATA_DESCRIPTOR descriptor{};
    descriptor.PropertyName = reinterpret_cast<ULONGLONG>(name);
    descriptor.ArrayIndex = ULONG_MAX;
    status = tdh.size(&event, 0, nullptr, 1, &descriptor, &bytes);
}

void rejectedShape(EVENT_RECORD& event, Result& result, Reject reason, const Tdh& tdh) {
    result.invalidSchedule = true;
    ++result.rejected;
    const auto& header = event.EventHeader;
    const auto& descriptor = header.EventDescriptor;
    const unsigned flags = header.Flags &
        (EVENT_HEADER_FLAG_CLASSIC_HEADER | EVENT_HEADER_FLAG_32_BIT_HEADER |
         EVENT_HEADER_FLAG_64_BIT_HEADER | EVENT_HEADER_FLAG_PROCESSOR_INDEX);
    for (size_t i = 0; i < result.shapeCount; ++i) {
        auto& shape = result.shapes[i];
        if (shape.opcode == descriptor.Opcode && shape.version == descriptor.Version &&
            shape.length == event.UserDataLength && shape.flags == flags && shape.reason == reason) {
            ++shape.count;
            return;
        }
    }
    if (result.shapeCount >= result.shapes.size()) { result.shapeOverflow = true; return; }
    auto& shape = result.shapes[result.shapeCount++];
    shape = {descriptor.Opcode, descriptor.Version, event.UserDataLength, flags, reason, 1};
    // The synthetic pure fixture has no real classic event header. Real
    // samples use only named size/status, never decoded field contents.
    if (reason != Unreadable && (flags & EVENT_HEADER_FLAG_CLASSIC_HEADER)) {
        const bool ready = descriptor.Opcode == 50;
        inspectSize(event, ready ? L"TThreadId" : L"NewThreadId", shape.firstStatus, shape.firstBytes, tdh);
        if (!ready) inspectSize(event, L"OldThreadId", shape.secondStatus, shape.secondBytes, tdh);
        inspectSize(event, ready ? L"Flag" : L"OldThreadState", shape.detailStatus, shape.detailBytes, tdh);
    }
}

const char* reasonName(Reject reason) {
    switch (reason) {
        case Unreadable: return "unreadable-target-prefix";
        case Version: return "unsupported-version";
        case Length: return "unexpected-payload-length";
        case SelfSwitch: return "target-switches-to-itself";
        case NamedSchema: return "v4-named-schema-unavailable-or-unsupported";
        case NamedRead: return "v4-named-size-or-read-failed";
        case NamedMismatch: return "v4-named-values-disagree";
    }
    return "unknown";
}

bool u32(const EVENT_RECORD& record, size_t offset, unsigned& value) {
    if (!record.UserData || record.UserDataLength < offset + sizeof(value)) return false;
    std::memcpy(&value, static_cast<const unsigned char*>(record.UserData) + offset, sizeof(value));
    return true;
}

template<class T>
bool named(EVENT_RECORD* event, const wchar_t* name, T& value, const Tdh& tdh = {}) {
    PROPERTY_DATA_DESCRIPTOR descriptor{};
    descriptor.PropertyName = reinterpret_cast<ULONGLONG>(name);
    descriptor.ArrayIndex = ULONG_MAX;
    ULONG bytes = 0;
    return tdh.size(event, 0, nullptr, 1, &descriptor, &bytes) == 0 && bytes == sizeof(T)
        && tdh.read(event, 0, nullptr, 1, &descriptor, bytes, reinterpret_cast<PBYTE>(&value)) == 0;
}

// Only bounded WBEM scalar metadata can corroborate the classic record.
struct Schema {
    alignas(TRACE_EVENT_INFO) std::array<unsigned char, 65536> buffer;
    ULONG bytes = 0;
    bool valid = false;

    const TRACE_EVENT_INFO& info() const {
        return *reinterpret_cast<const TRACE_EVENT_INFO*>(buffer.data());
    }

    Schema(EVENT_RECORD* event, const Tdh& tdh) {
        constexpr auto header = offsetof(TRACE_EVENT_INFO, EventPropertyInfoArray);
        if (tdh.info(event, 0, nullptr, nullptr, &bytes) != ERROR_INSUFFICIENT_BUFFER ||
            bytes < header || bytes > buffer.size()) return;
        const auto requestedBytes = bytes;
        if (tdh.info(event, 0, nullptr,
                reinterpret_cast<TRACE_EVENT_INFO*>(buffer.data()), &bytes) != ERROR_SUCCESS ||
            bytes < header || bytes > requestedBytes) return;
        valid = info().DecodingSource == DecodingSourceWbem &&
            info().PropertyCount <= (bytes - header) / sizeof(EVENT_PROPERTY_INFO) &&
            info().TopLevelPropertyCount <= info().PropertyCount;
    }

    unsigned type(std::wstring_view name) const {
        if (!valid) return 0;
        const auto namesBegin = offsetof(TRACE_EVENT_INFO, EventPropertyInfoArray) +
            info().PropertyCount * sizeof(EVENT_PROPERTY_INFO);
        unsigned result = 0;
        bool found = false;
        for (ULONG i = 0; i < info().TopLevelPropertyCount; ++i) {
            const auto& entry = info().EventPropertyInfoArray[i];
            const auto offset = entry.NameOffset;
            if (offset < namesBegin || offset >= bytes || offset % alignof(wchar_t) ||
                (bytes - offset) / sizeof(wchar_t) <= name.size()) continue;
            const auto* label = reinterpret_cast<const wchar_t*>(buffer.data() + offset);
            if (label[name.size()] != L'\0' || std::wstring_view(label, name.size()) != name) continue;
            constexpr unsigned scalarFlags = PropertyParamFixedLength | PropertyHasTags;
            if (found || entry.count != 1 || (entry.Flags & ~scalarFlags)) return 0;
            found = true;
            result = entry.nonStructType.InType;
        }
        return result;
    }
};

constexpr wchar_t newThreadName[] = L"NewThreadId";
constexpr wchar_t oldThreadName[] = L"OldThreadId";
constexpr wchar_t oldStateName[] = L"OldThreadState";
bool lifetime(const std::array<Life, 8>& records, size_t count, const Request& request) {
    return count == 2 && records[0].kind == 3 && records[1].kind == 4
        && records[0].tick > 0 && records[0].tick <= request.active && request.followingPoll < records[1].tick
        && records[0].key != 0 && records[0].key == records[1].key;
}

void onLife(EVENT_RECORD* event, Result& result, bool process) {
    const auto& header = event->EventHeader;
    const auto& desc = header.EventDescriptor;
    const unsigned pid = result.request.pid, tid = result.request.tid;
    const bool width64 = (header.Flags & EVENT_HEADER_FLAG_64_BIT_HEADER) != 0;
    const bool width32 = (header.Flags & EVENT_HEADER_FLAG_32_BIT_HEADER) != 0;
    if (width64 == width32) { result.invalidLife = true; return; }
    unsigned owner = 0, thread = 0;
    if (!u32(*event, process ? (width64 ? 8 : 4) : 0, owner)
        || (!process && !u32(*event, 4, thread))) { result.invalidLife = true; return; }
    // Catch reuse of the target TID by any PID; never retain another PID.
    if ((process && owner != pid) || (!process && thread != tid)) return;
    if (owner != pid || !width64 || desc.Version != (process ? 4 : 3)) {
        result.invalidLife = true;
        return;
    }
    unsigned namedPid = 0, namedTid = 0;
    unsigned long long key = tid;
    if (!named(event, L"ProcessId", namedPid) || namedPid != pid) {
        result.invalidLife = true;
        return;
    }
    if (process) {
        unsigned long long prefixKey = 0;
        std::memcpy(&prefixKey, event->UserData, sizeof(prefixKey));
        if (!named(event, L"UniqueProcessKey", key) || !key || key != prefixKey) {
            result.invalidLife = true;
            return;
        }
    } else if (!named(event, L"TThreadId", namedTid) || namedTid != tid) {
        result.invalidLife = true;
        return;
    }
    auto& records = process ? result.processes : result.threads;
    auto& count = process ? result.np : result.nt;
    if (count == records.size()) { result.invalidLife = true; return; }
    records[count++] = {header.TimeStamp.QuadPart, desc.Opcode, key};
}

void onSchedule(EVENT_RECORD* event, Result& result,
                const Tdh& tdh = {}) {
    const auto& header = event->EventHeader;
    const auto& desc = header.EventDescriptor;
    const auto tick = header.TimeStamp.QuadPart;
    if (tick < result.request.lower || tick > result.request.upper) return;
    const auto tid = result.request.tid;
    const bool ready = desc.Opcode == 50;
    unsigned first = 0, second = 0;
    if (!u32(*event, 0, first) || (!ready && !u32(*event, 4, second))) {
        rejectedShape(*event, result, Unreadable, tdh);
        return;
    }
    if (first != tid && second != tid) return;
    const bool v4 = desc.Version == 4 && desc.Opcode == 36 &&
        (header.Flags & EVENT_HEADER_FLAG_CLASSIC_HEADER) && IsEqualGUID(header.ProviderId, threadGuid);
    if (desc.Version != 2 && !v4) {
        rejectedShape(*event, result, Version, tdh);
        return;
    }
    if (v4) ++result.v4Candidates;
    if (event->UserDataLength != (ready ? 8 : 24)) {
        rejectedShape(*event, result, Length, tdh);
        return;
    }
    const bool boundary = !ready && first == tid && second == tid;
    if (boundary && !v4) {
        rejectedShape(*event, result, SelfSwitch, tdh);
        return;
    }
    const auto* data = static_cast<const unsigned char*>(event->UserData);
    if (v4) {
        ++result.v4Checked;
        const Schema schema(event, tdh);
        if (schema.type(newThreadName) != TDH_INTYPE_UINT32 ||
            schema.type(oldThreadName) != TDH_INTYPE_UINT32 ||
            schema.type(oldStateName) != TDH_INTYPE_INT8) {
            rejectedShape(*event, result, NamedSchema, tdh);
            return;
        }
        ++result.v4Schema;
        unsigned namedNew = 0, namedOld = 0;
        unsigned char namedState = 0; // Compare the full signed field's wire byte.
        if (!named(event, newThreadName, namedNew, tdh) ||
            !named(event, oldThreadName, namedOld, tdh) ||
            !named(event, oldStateName, namedState, tdh)) {
            rejectedShape(*event, result, NamedRead, tdh);
            return;
        }
        if (namedNew != first || namedOld != second || namedState != data[14]) {
            rejectedShape(*event, result, NamedMismatch, tdh);
            return;
        }
        ++result.v4Corroborated;
    }
    if (boundary && data[14] != 2) {
        rejectedShape(*event, result, SelfSwitch, tdh);
        return;
    }
    if (result.size == result.events.size()) { result.overflow = true; return; }
    if (v4) ++result.v4Accepted;
    if (boundary) ++result.boundaryRecords;
    const auto cpu = header.Flags & EVENT_HEADER_FLAG_PROCESSOR_INDEX
        ? event->BufferContext.ProcessorIndex : event->BufferContext.ProcessorNumber;
    // Do not compare a legacy processor number to a full processor index.
    const auto cpuIdentity = static_cast<unsigned>(cpu) |
        (header.Flags & EVENT_HEADER_FLAG_PROCESSOR_INDEX ? 0x10000U : 0U);
    result.events[result.size++] = {tick, boundary ? 'B' : ready ? 'R' : first == tid ? 'I' : 'O',
        cpuIdentity, ready ? data[6] : second == tid ? data[14] : 0U};
}

void WINAPI receive(EVENT_RECORD* event) {
    const auto& header = event->EventHeader;
    if (!(header.Flags & EVENT_HEADER_FLAG_CLASSIC_HEADER)) return;
    const auto opcode = header.EventDescriptor.Opcode;
    auto& result = *static_cast<Result*>(event->UserContext);
    if (IsEqualGUID(header.ProviderId, processGuid) && ((opcode >= 1 && opcode <= 4) || opcode == 39))
        onLife(event, result, true);
    if (!IsEqualGUID(header.ProviderId, threadGuid)) return;
    if (opcode >= 1 && opcode <= 4) onLife(event, result, false);
    if (opcode == 36 || opcode == 50) onSchedule(event, result);
}

const char* flag(bool value) { return value ? "true" : "false"; }

bool number(const wchar_t* text, unsigned long long maximum, unsigned long long& value) {
    if (!*text || std::wcsspn(text, L"0123456789") != std::wcslen(text)) return false;
    errno = 0;
    value = std::wcstoull(text, nullptr, 10);
    return !errno && value && value <= maximum;
}

int writeReport(const Result& result, const TRACE_LOGFILE_HEADER& header) {
    const bool process = lifetime(result.processes, result.np, result.request);
    const bool thread = lifetime(result.threads, result.nt, result.request);
    const bool clock = header.ReservedFlags == 1 && header.PerfFreq.QuadPart == result.request.qpf;
    const bool loss = header.EventsLost || header.BuffersLost;
    const bool available = process && thread && !result.invalidLife && clock && !loss
        && !result.invalidSchedule && !result.overflow;
    std::printf("{\"WireSchema\":2,\"BoundaryRecords\":%zu,\"ProcessPair\":%s,\"ThreadPair\":%s,\"ClockMatches\":%s,\"Loss\":%s,"
        "\"HeaderClockType\":%lu,\"HeaderQpf\":%lld,\"HeaderEventsLost\":%lu,\"HeaderBuffersLost\":%lu,"
        "\"InvalidLifecycle\":%s,\"InvalidScheduler\":%s,\"Overflow\":%s,\"Candidates\":%zu,"
        "\"V4Candidates\":%zu,\"V4Checked\":%zu,\"V4Schema\":%zu,\"V4Corroborated\":%zu,\"V4Accepted\":%zu,"
        "\"RejectedSchedulerRecords\":%zu,\"ShapeOverflow\":%s,\"RejectedShapes\":[",
        result.boundaryRecords, flag(process), flag(thread), flag(clock), flag(loss), header.ReservedFlags, header.PerfFreq.QuadPart,
        header.EventsLost, header.BuffersLost, flag(result.invalidLife),
        flag(result.invalidSchedule), flag(result.overflow), result.size,
        result.v4Candidates, result.v4Checked, result.v4Schema, result.v4Corroborated, result.v4Accepted,
        result.rejected, flag(result.shapeOverflow));
    for (size_t i = 0; i < result.shapeCount; ++i) {
        const auto& shape = result.shapes[i];
        std::printf("%s{\"Opcode\":%u,\"Version\":%u,\"Length\":%u,\"HeaderFlags\":%u,"
                    "\"Reason\":\"%s\",\"Count\":%zu,\"FirstStatus\":%lu,\"FirstBytes\":%lu,"
                    "\"SecondStatus\":%lu,\"SecondBytes\":%lu,\"DetailStatus\":%lu,\"DetailBytes\":%lu}",
                    i ? "," : "", shape.opcode, shape.version, shape.length, shape.flags, reasonName(shape.reason),
                    shape.count, shape.firstStatus, shape.firstBytes, shape.secondStatus, shape.secondBytes,
                    shape.detailStatus, shape.detailBytes);
    }
    std::fputs("],\"Events\":[", stdout);
    for (size_t i = 0; available && i < result.size; ++i) {
        const auto& e = result.events[i];
        std::printf("%s{\"Tick\":%lld,\"Kind\":\"%c\",\"Cpu\":%u,\"Detail\":%u}", i ? "," : "",
                    e.tick,e.kind,e.cpu,e.detail);
    }
    std::puts("]}");
    std::puts(available ? "COMPLETE raw gameplay scheduler evidence" :
                         "INCONCLUSIVE raw gameplay scheduler evidence");
    return available ? 0 : 3;
}
}
int wmain(int argc, wchar_t** argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    if (argc != 11) return 1;
    const unsigned long long maxima[] = {UINT_MAX, UINT_MAX, LLONG_MAX, LLONG_MAX, LLONG_MAX,
                                        LLONG_MAX, LLONG_MAX, maxEvents, 256ULL * 1024 * 1024};
    unsigned long long values[9]{};
    for (int i = 0; i < 9; ++i) {
        if (!number(argv[i + 2], maxima[i], values[i])) return 1;
    }
    const Request request{static_cast<unsigned>(values[0]), static_cast<unsigned>(values[1]),
        static_cast<long long>(values[2]), static_cast<long long>(values[3]), static_cast<long long>(values[4]),
        static_cast<long long>(values[5]), static_cast<long long>(values[6]), static_cast<size_t>(values[7])};
    if (!(request.active <= request.lower && request.lower < request.upper &&
          request.upper < request.followingPoll)) return 1;
    WIN32_FILE_ATTRIBUTE_DATA file{};
    if (!GetFileAttributesExW(argv[1], GetFileExInfoStandard, &file) ||
        (file.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) ||
        file.nFileSizeHigh || !file.nFileSizeLow || file.nFileSizeLow >= values[8]) return 1;
    Result result(request);
    EVENT_TRACE_LOGFILEW log{};
    log.LogFileName = argv[1];
    log.ProcessTraceMode = PROCESS_TRACE_MODE_EVENT_RECORD | PROCESS_TRACE_MODE_RAW_TIMESTAMP;
    log.EventRecordCallback = receive;
    log.Context = &result;
    auto handle = OpenTraceW(&log);
    if (handle == INVALID_PROCESSTRACE_HANDLE) return 1;
    const auto status = ProcessTrace(&handle, 1, nullptr, nullptr);
    const auto closed = CloseTrace(handle);
    if (status != ERROR_SUCCESS || closed != ERROR_SUCCESS) return 1;
    return writeReport(result, log.LogfileHeader);
}
