#define wmain readerMain
#include "../tools/gameplay-raw-reader/witness.cpp"
#undef wmain

namespace {
constexpr Request input{100, 101, 1000, 22, 100, 25, 99, 16};
constexpr auto tid = input.tid;
constexpr auto lower = input.lower;
int check() {
    std::array<Life,8> pair{{{21,3,0xff00123456789abcULL},{110,4,0xff00123456789abcULL}}};
    if (!lifetime(pair,2,input) || lifetime(pair,1,input) || lifetime(pair,3,input)) return 1;
    pair[1].key = 0x0000123456789abcULL;
    if (lifetime(pair,2,input)) return 1;
    pair[1] = pair[0];
    if (lifetime(pair,2,input)) return 1;
    pair[1] = {100,4,pair[0].key};
    if (lifetime(pair,2,input)) return 1;
    std::array<unsigned char,24> bytes{};
    std::memcpy(bytes.data(), &tid, sizeof(tid));
    EVENT_RECORD record{};
    record.UserData = bytes.data();
    record.UserDataLength = static_cast<USHORT>(bytes.size());
    record.EventHeader.EventDescriptor.Opcode = 36;
    record.EventHeader.EventDescriptor.Version = 2;
    record.EventHeader.TimeStamp.QuadPart = lower;
    Result result(input);
    onSchedule(&record,result);
    if (result.size != 1 || result.events[0].kind != 'I' || result.invalidSchedule) return 1;
    record.EventHeader.EventDescriptor.Version = 3;
    onSchedule(&record,result);
    onSchedule(&record,result);
    if (!result.invalidSchedule || result.size != 1 || result.rejected != 2 || result.shapeCount != 1
        || result.shapes[0].reason != Version || result.shapes[0].count != 2) return 1;
    record.EventHeader.EventDescriptor.Version = 2;
    record.UserDataLength = 3;
    onSchedule(&record,result);
    if (result.shapes[1].reason != Unreadable || result.shapeCount != 2) return 1;
    record.UserDataLength = 23;
    onSchedule(&record,result);
    if (result.shapes[2].reason != Length || result.shapeCount != 3) return 1;
    record.UserDataLength = 24;
    std::memcpy(bytes.data() + 4, &tid, sizeof(tid));
    onSchedule(&record,result);
    if (result.shapes[3].reason != SelfSwitch || result.shapeCount != 4 || result.size != 1) return 1;
    record.EventHeader.EventDescriptor.Opcode = 50;
    record.UserDataLength = 8;
    onSchedule(&record,result);
    if (result.size != 2 || result.events[1].kind != 'R') return 1;
    for (unsigned i = 10; i < 30; ++i) {
        record.EventHeader.EventDescriptor.Version = static_cast<UCHAR>(i);
        onSchedule(&record,result);
    }
    if (!result.shapeOverflow || result.shapeCount != result.shapes.size() || result.rejected != 25) return 1;
    std::puts("COMPLETE raw witness shape predicates cases=11");
    return 0;
}
struct Fixture {
    unsigned newThread, oldThread;
    unsigned char oldState;
    unsigned stateType = TDH_INTYPE_INT8;
    PROPERTY_FLAGS stateFlags{};
    USHORT stateCount = 1;
    enum Fault { None, SchemaQuery, SchemaCap, SchemaMissing, SchemaDuplicate, SizeQuery, SizeWrong, ReadQuery };
    Fault fault = None;
};

Fixture fixture{};

ULONG WINAPI fixtureInfo(PEVENT_RECORD, ULONG, PTDH_CONTEXT, PTRACE_EVENT_INFO info, PULONG bytes) {
    constexpr ULONG labels = offsetof(TRACE_EVENT_INFO, EventPropertyInfoArray) + 3 * sizeof(EVENT_PROPERTY_INFO);
    constexpr ULONG required = labels + sizeof(newThreadName) + sizeof(oldThreadName) + sizeof(oldStateName);
    if (!info) {
        if (fixture.fault == Fixture::SchemaQuery) return ERROR_NOT_FOUND;
        *bytes = fixture.fault == Fixture::SchemaCap ? 65537 : required;
        return ERROR_INSUFFICIENT_BUFFER;
    }
    if (*bytes < required) return ERROR_INSUFFICIENT_BUFFER;
    *bytes = required;
    std::memset(info, 0, required);
    info->DecodingSource = DecodingSourceWbem;
    info->PropertyCount = info->TopLevelPropertyCount = 3;
    auto* data = reinterpret_cast<unsigned char*>(info);
    auto* properties = reinterpret_cast<EVENT_PROPERTY_INFO*>(
        data + offsetof(TRACE_EVENT_INFO, EventPropertyInfoArray));
    const wchar_t* names[] = {newThreadName, oldThreadName, oldStateName};
    ULONG offset = labels;
    for (unsigned i = 0; i < 3; ++i) {
        auto& field = properties[i];
        const auto bytesForName = static_cast<ULONG>((std::wcslen(names[i]) + 1) * sizeof(wchar_t));
        field.NameOffset = offset;
        field.count = 1;
        field.nonStructType.InType = TDH_INTYPE_UINT32;
        std::memcpy(data + offset, names[i], bytesForName);
        offset += bytesForName;
    }
    auto& state = properties[2];
    state.Flags = fixture.stateFlags;
    state.count = fixture.stateCount;
    state.nonStructType.InType = static_cast<USHORT>(fixture.stateType);
    if (fixture.fault == Fixture::SchemaMissing) state.NameOffset = required;
    if (fixture.fault == Fixture::SchemaDuplicate) state.NameOffset = properties[0].NameOffset;
    return ERROR_SUCCESS;
}

ULONG WINAPI fixtureSize(PEVENT_RECORD, ULONG, PTDH_CONTEXT, ULONG, PPROPERTY_DATA_DESCRIPTOR property,
                        PULONG bytes) {
    if (fixture.fault == Fixture::SizeQuery) return ERROR_NOT_FOUND;
    const auto* name = reinterpret_cast<const wchar_t*>(property->PropertyName);
    *bytes = std::wcscmp(name, oldStateName) == 0 ? 1 : 4;
    if (fixture.fault == Fixture::SizeWrong && *bytes == 1) *bytes = 2;
    return ERROR_SUCCESS;
}

ULONG WINAPI fixtureRead(PEVENT_RECORD, ULONG, PTDH_CONTEXT, ULONG, PPROPERTY_DATA_DESCRIPTOR property,
                        ULONG bytes, PBYTE value) {
    if (fixture.fault == Fixture::ReadQuery) return ERROR_NOT_FOUND;
    const auto* name = reinterpret_cast<const wchar_t*>(property->PropertyName);
    const void* source = &fixture.oldState;
    if (std::wcscmp(name, newThreadName) == 0) source = &fixture.newThread;
    if (std::wcscmp(name, oldThreadName) == 0) source = &fixture.oldThread;
    std::memcpy(value, source, bytes);
    return ERROR_SUCCESS;
}

int checkV4() {
    constexpr unsigned other = 0xf2345678;
    std::array<unsigned char, 25> bytes{};
    std::memcpy(bytes.data(), &other, sizeof(other));
    std::memcpy(bytes.data() + 4, &tid, sizeof(tid));
    bytes[14] = 0x81;
    EVENT_RECORD record{};
    record.EventHeader.ProviderId = threadGuid;
    record.EventHeader.Flags = EVENT_HEADER_FLAG_CLASSIC_HEADER | EVENT_HEADER_FLAG_64_BIT_HEADER |
        EVENT_HEADER_FLAG_PROCESSOR_INDEX;
    record.EventHeader.EventDescriptor.Opcode = 36;
    record.EventHeader.EventDescriptor.Version = 4;
    record.EventHeader.TimeStamp.QuadPart = lower;
    record.BufferContext.ProcessorIndex = 257;
    record.UserData = bytes.data();
    record.UserDataLength = 24;
    const Fixture matched{other, tid, bytes[14]};
    const Tdh inert{fixtureInfo, fixtureSize, fixtureRead};
    fixture = matched;
    Result accepted(input);
    onSchedule(&record, accepted, inert);
    const auto& first = accepted.events[0];
    if (accepted.size != 1 || accepted.invalidSchedule || accepted.v4Accepted != 1 ||
        accepted.v4Candidates != 1 || accepted.v4Checked != 1 || accepted.v4Schema != 1 ||
        accepted.v4Corroborated != 1 || first.kind != 'O' || first.detail != bytes[14] ||
        first.cpu != 0x10101U) return 1;
    const auto rejects = [&](Reject reason) {
        Result rejected(input);
        onSchedule(&record, rejected, inert);
        return rejected.size == 0 && rejected.invalidSchedule && rejected.v4Accepted == 0 &&
            rejected.rejected == 1 && rejected.shapes[0].reason == reason;
    };
    for (auto fault : {Fixture::SchemaQuery, Fixture::SchemaCap, Fixture::SchemaMissing, Fixture::SchemaDuplicate}) {
        fixture.fault = fault;
        if (!rejects(NamedSchema)) return 1;
    }
    fixture = matched;
    fixture.stateType = TDH_INTYPE_UINT8;
    if (!rejects(NamedSchema)) return 1;
    fixture = matched;
    fixture.stateFlags = PropertyStruct;
    if (!rejects(NamedSchema)) return 1;
    fixture.stateFlags = PropertyParamCount;
    if (!rejects(NamedSchema)) return 1;
    fixture = matched;
    fixture.stateCount = 2;
    if (!rejects(NamedSchema)) return 1;
    fixture = matched;
    for (auto fault : {Fixture::SizeQuery, Fixture::SizeWrong, Fixture::ReadQuery}) {
        fixture.fault = fault;
        if (!rejects(NamedRead)) return 1;
    }
    fixture = matched;
    fixture.newThread ^= 0x80000000U;
    if (!rejects(NamedMismatch)) return 1;
    fixture = matched;
    fixture.oldThread ^= 0x80000000U;
    if (!rejects(NamedMismatch)) return 1;
    fixture = matched;
    fixture.oldState ^= 0x80;
    if (!rejects(NamedMismatch)) return 1;
    fixture = matched;
    record.UserData = nullptr;
    if (!rejects(Unreadable)) return 1;
    record.UserData = bytes.data();
    record.UserDataLength = 7;
    if (!rejects(Unreadable)) return 1;
    record.UserDataLength = 23;
    if (!rejects(Length)) return 1;
    record.UserDataLength = 25;
    if (!rejects(Length)) return 1;
    record.UserDataLength = 24;
    record.EventHeader.EventDescriptor.Version = 5;
    if (!rejects(Version)) return 1;
    record.EventHeader.EventDescriptor.Version = 4;
    record.EventHeader.EventDescriptor.Opcode = 50;
    std::memcpy(bytes.data(), &tid, sizeof(tid));
    if (!rejects(Version)) return 1;
    record.EventHeader.EventDescriptor.Opcode = 36;
    record.EventHeader.Flags &= ~EVENT_HEADER_FLAG_CLASSIC_HEADER;
    if (!rejects(Version)) return 1;
    record.EventHeader.Flags |= EVENT_HEADER_FLAG_CLASSIC_HEADER;
    record.EventHeader.ProviderId = processGuid;
    if (!rejects(Version)) return 1;
    record.EventHeader.ProviderId = threadGuid;
    fixture.newThread = tid;
    if (!rejects(SelfSwitch)) return 1;
    fixture = matched;
    std::memcpy(bytes.data(), &other, sizeof(other));
    Result full(input);
    full.size = input.events;
    onSchedule(&record, full, inert);
    if (!full.overflow || full.v4Accepted || full.v4Corroborated != 1 || full.size != input.events) return 1;
    std::memcpy(bytes.data() + 4, &other, sizeof(other));
    Result unrelated(input);
    onSchedule(&record, unrelated, inert);
    if (unrelated.v4Candidates || unrelated.invalidSchedule || unrelated.size) return 1;
    std::puts("COMPLETE strict CSwitch v4 predicates cases=26");
    return 0;
}

}

int wmain(int argc, wchar_t** argv) {
    std::array<unsigned char, 24> bytes{};
    std::memcpy(bytes.data(), &tid, sizeof(tid));
    std::memcpy(bytes.data() + 4, &tid, sizeof(tid));
    bytes[14] = 2;
    EVENT_RECORD record{};
    record.EventHeader.ProviderId = threadGuid;
    record.EventHeader.Flags = EVENT_HEADER_FLAG_CLASSIC_HEADER | EVENT_HEADER_FLAG_64_BIT_HEADER |
        EVENT_HEADER_FLAG_PROCESSOR_INDEX;
    record.EventHeader.EventDescriptor.Opcode = 36;
    record.EventHeader.EventDescriptor.Version = 4;
    record.EventHeader.TimeStamp.QuadPart = lower;
    record.BufferContext.ProcessorIndex = 257;
    record.UserData = bytes.data();
    record.UserDataLength = static_cast<USHORT>(bytes.size());
    const Tdh inert{fixtureInfo, fixtureSize, fixtureRead};
    const Fixture match{tid, tid, bytes[14]};
    fixture = match;
    Result result(input);
    onSchedule(&record, result, inert);
    if (!result.size || result.events[0].kind != 'B' || result.events[0].detail != 2 ||
        result.events[0].cpu != 0x10101 || result.invalidSchedule || result.boundaryRecords != 1 ||
        result.v4Accepted != 1 || result.v4Corroborated != 1) return 1;
    if (argc == 2) {
        result.processes[0] = {21,3,8}; result.processes[1] = {110,4,8};
        result.threads[0] = {21,3,tid}; result.threads[1] = {110,4,tid};
        result.np = result.nt = 2;
        TRACE_LOGFILE_HEADER header{};
        header.ReservedFlags = 1;
        header.PerfFreq.QuadPart = input.qpf;
        if (std::wcscmp(argv[1], L"--loss") == 0) header.EventsLost = 1;
        else if (std::wcscmp(argv[1], L"--lifecycle") == 0) result.threads[1].key ^= 1;
        else if (std::wcscmp(argv[1], L"--overflow") == 0) {
            for (size_t i = 0; i < input.events; ++i) onSchedule(&record, result, inert);
        } else if (std::wcscmp(argv[1], L"--sticky") == 0) {
            bytes[14] = 3;
            fixture.oldState = 3;
            onSchedule(&record, result, inert);
            bytes[14] = 2;
            fixture = match;
            onSchedule(&record, result, inert);
        } else if (std::wcscmp(argv[1], L"--emit") != 0) return 1;
        return writeReport(result, header);
    }
    if (argc != 1 || check() || checkV4()) return 1;
    const auto refuses = [&](Reject reason) {
        Result denied(input);
        onSchedule(&record, denied, inert);
        return denied.invalidSchedule && denied.rejected == 1 && denied.shapes[0].reason == reason &&
            !denied.size && !denied.v4Accepted && !denied.boundaryRecords;
    };
    fixture.oldThread ^= 0x80000000U;
    if (!refuses(NamedMismatch)) return 1;
    fixture = match;
    fixture.newThread ^= 0x80000000U;
    if (!refuses(NamedMismatch)) return 1;
    fixture = match;
    fixture.oldState ^= 0x80;
    if (!refuses(NamedMismatch)) return 1;
    for (auto fault : {Fixture::SchemaMissing, Fixture::SchemaDuplicate, Fixture::SchemaCap}) {
        fixture = match; fixture.fault = fault;
        if (!refuses(NamedSchema)) return 1;
    }
    fixture = match; fixture.stateCount = 2;
    if (!refuses(NamedSchema)) return 1;
    fixture = match; fixture.stateType = TDH_INTYPE_UINT8;
    if (!refuses(NamedSchema)) return 1;
    for (auto fault : {Fixture::SizeWrong, Fixture::SizeQuery, Fixture::ReadQuery}) {
        fixture = match; fixture.fault = fault;
        if (!refuses(NamedRead)) return 1;
    }
    fixture = match;
    bytes[14] = fixture.oldState = 3;
    if (!refuses(SelfSwitch)) return 1;
    record.EventHeader.EventDescriptor.Version = 2;
    if (!refuses(SelfSwitch)) return 1;
    record.EventHeader.EventDescriptor.Version = 3;
    if (!refuses(Version)) return 1;
    record.EventHeader.EventDescriptor.Version = 4;
    record.UserDataLength = 23;
    if (!refuses(Length)) return 1;
    std::puts("COMPLETE private boundary native predicates");
    return 0;
}
