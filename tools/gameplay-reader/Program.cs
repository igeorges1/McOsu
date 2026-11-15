using System.Buffers.Binary;
using System.Text.Json;
using Microsoft.Windows.EventTracing;
using Microsoft.Windows.EventTracing.Cpu;
using Microsoft.Windows.EventTracing.Processes;

if (args is ["--check-boundaries"]) return Boundaries.Check();
if (args is ["--check-identity-diagnostics"]) return IdentityDiagnostics.Check();
if (args is ["--check-process-key-diagnostics"]) return IdentityDiagnostics.CheckProcessKey();
if (args.Length != 2) return 2;
var request = JsonSerializer.Deserialize<Request>(File.ReadAllText(args[0])) ?? throw new InvalidDataException();
if (request.InputLimit is <= 0 or > 268435456 || request.SliceLimit is <= 0 or > 131072 ||
    new FileInfo(args[1]).Length is <= 0 || new FileInfo(args[1]).Length >= request.InputLimit)
    return 2;
using var trace = TraceProcessor.Create(args[1], new TraceProcessorSettings
{
    SuppressFirstTimeSetupMessage = true, AllowLostEvents = true
});
var metadata = trace.UseMetadata();
var processes = trace.UseProcesses();
var threads = trace.UseThreads();
var switching = trace.UseContextSwitchData();
var readiness = trace.UseReadyThreadData();
var scheduler = trace.UseCpuSchedulingData();
var boundaries = new Boundaries(request.Pid, request.Tid);
boundaries.Register(trace);
trace.Process();
var models = processes.Result.Processes.Where(p => p.Id == request.Pid).Take(2).ToArray();
var process = models.Length == 1 ? models[0] : null;
bool Owns(IThread? t) => t is not null && process is not null && t.Id == request.Tid && ReferenceEquals(t.Process, process);
var creation = process?.CreateTime;
long? delta = creation is { HasValue: true } created
    ? Math.Abs(created.DateTimeOffset.ToFileTime() - request.Creation) : null;
bool clockMatches = metadata.ClockType.ToString() == "PerformanceCounter";
bool frequencyMatches = metadata.PerformanceCounterFrequency.ToString() == $"{request.Qpf} Hz";
bool noLoss = metadata.LostBufferCount == 0 && metadata.LostEventCount == 0;
var targetThreads = threads.Result.Threads.Where(thread => thread.Id == request.Tid);
int ownedThreads = targetThreads.Count(Owns);
bool trusted = clockMatches && frequencyMatches && noLoss && IdentityDiagnostics.CreationMatches(delta)
    && ownedThreads == 1;
var processLife = boundaries.ProcessWindow();
var threadLife = boundaries.ThreadWindow();
ulong? managedKey = process is null ? null : unchecked((ulong)process.ObjectAddress.Value);
var lower = Math.Max(request.Active, Math.Max(processLife.Start, threadLife.Start));
var upper = Math.Min(request.Stop, Math.Min(processLife.End, threadLife.End));
var slices = new List<Slice>();
bool overflow = false;
bool CanFit(long a, long b) => lower <= a && a <= b && b <= upper;
void Add(string state, long start, long end, int? cpu, long off, long? ready, long next)
{
    if (start >= end || end <= request.First || start >= request.Last) return;
    if (slices.Count == request.SliceLimit) { overflow = true; return; }
    slices.Add(new(state, start, end, cpu, off, ready, next));
}
var context = new HashSet<(long Tick, int Cpu, bool In)>();
var readyTicks = new HashSet<long>();
int evidenceLimit = request.SliceLimit * 4;
if (trusted && lower < upper)
{
    foreach (var evt in switching.Result.ContextSwitches)
    {
        if (Tick(evt.Timestamp) is not long tick || tick < lower || tick > upper) continue;
        if (evt.SwitchIn.ThreadId == request.Tid) context.Add((tick, evt.Processor, true));
        if (evt.SwitchOut.ThreadId == request.Tid) context.Add((tick, evt.Processor, false));
        if (context.Count > evidenceLimit) { overflow = true; break; }
    }
    foreach (var evt in readiness.Result.ReadyThreadEvents)
    {
        if (evt.ReadiedThreadId == request.Tid && Tick(evt.Timestamp) is long tick && lower <= tick && tick <= upper)
            readyTicks.Add(tick);
        if (readyTicks.Count > evidenceLimit) { overflow = true; break; }
    }
    if (!overflow)
    {
        foreach (var slice in scheduler.Result.CpuTimeSlices)
        {
            if (Owns(slice.Thread) && Tick(slice.StartTime) is long a && Tick(slice.StopTime) is long b
                && CanFit(a, b) && context.Contains((a, slice.Processor, true)) && context.Contains((b, slice.Processor, false)))
                Add("running", a, b, slice.Processor, a, null, b);
            if (overflow) break;
        }
        foreach (var activity in scheduler.Result.ThreadActivity)
        {
            if (overflow) break;
            if (!Owns(activity.Thread) || activity.PreviousActivity is not { } prior
                || Tick(prior.StopTime) is not long a || Tick(activity.StartTime) is not long c
                || !CanFit(a, c) || !context.Contains((a, prior.Processor, false))
                || !context.Contains((c, activity.Processor, true))) continue;
            string? state = prior.SwitchOut?.ThreadState?.ToString();
            if (state == "Ready") Add("ready", a, c, null, a, a, c);
            if (state == "Waiting" && activity.ReadyThreadEvent is { } transition
                && Tick(transition.Timestamp) is long b && a < b && b <= c && readyTicks.Contains(b))
            {
                Add("waiting", a, b, null, a, b, c);
                Add("ready", b, c, null, a, b, c);
            }
        }
    }
}
var ordered = slices.OrderBy(slice => slice.Start).ThenBy(slice => slice.End).ToArray();
bool overlap = ordered.Zip(ordered.Skip(1), (a, b) => a.End > b.Start).Any(value => value);
bool usable = trusted && lower < upper && !overflow && !overlap;
Console.WriteLine(JsonSerializer.Serialize(new
{
    Clock = metadata.ClockType.ToString(), Qpf = metadata.PerformanceCounterFrequency.ToString(),
    metadata.LostEventCount, metadata.LostBufferCount, Process = processLife, Thread = threadLife,
    Lower = lower, Upper = upper, CreationDelta = delta, Usable = usable, Overflow = overflow,
    Overlap = overlap,
    IdentityDiagnostics = new
    {
        // Both model counts saturate at two. Never emit other processes, paths or raw kernel addresses.
        TargetProcessModelsUpToTwo = models.Length,
        TargetThreadModelsUpToTwo = targetThreads.Take(2).Count(),
        OwnedThreadModels = ownedThreads,
        CreationHasValue = creation?.HasValue,
        CreationIsPartial = creation is { HasValue: true } ? creation.Value.IsPartial : (bool?)null,
        CreationProvenance = IdentityDiagnostics.CreationProvenance(models.Length,
            creation is { HasValue: true }, creation is { HasValue: true, IsPartial: true }),
        ManagedImageNamePresent = process is null ? (bool?)null : !string.IsNullOrEmpty(process.ImageName),
        ManagedProcessKeyMatches = process is null || processLife == default ? (bool?)null
            : boundaries.ProcessKeyMatches(managedKey!.Value),
        ProcessKeyProvenance = IdentityDiagnostics.ProcessKeyProvenance(managedKey,
            processLife != default, managedKey.HasValue && boundaries.ProcessKeyMatches(managedKey.Value)),
        RawProcessBoundaries = boundaries.ProcessEvidence,
        RawThreadBoundaries = boundaries.ThreadEvidence,
        RawProcessCoversActive = processLife.Start <= request.Active && request.Active < request.Stop
            && request.Stop <= processLife.End,
        RawThreadCoversActive = threadLife.Start <= request.Active && request.Active < request.Stop
            && request.Stop <= threadLife.End,
        Gates = new
        {
            Clock = clockMatches, Frequency = frequencyMatches, NoLoss = noLoss,
            UniqueProcessModel = process is not null, UniqueOwnedThreadModel = ownedThreads == 1,
            CreationWithinTolerance = IdentityDiagnostics.CreationMatches(delta),
            RawProcessWindow = processLife != default, RawThreadWindow = threadLife != default,
            NonemptyIntersection = lower < upper
        }
    },
    Slices = usable ? ordered : Array.Empty<Slice>()
}));
Console.WriteLine(usable ? "COMPLETE gameplay scheduler evidence" : "INCONCLUSIVE gameplay scheduler evidence");
return usable ? 0 : 3;

static long? Tick(TraceTimestamp? value) => value is { HasValue: true, IsPartial: false } time ? time.Value.RawValue : null;

record Request(int Pid, int Tid, long Creation, long Qpf, long Active, long Stop, long First, long Last,
               long InputLimit, int SliceLimit);
record Slice(string State, long Start, long End, int? Cpu, long Off, long? Ready, long Next);

static class IdentityDiagnostics
{
    internal static bool CreationMatches(long? delta) => delta is >= 0 and <= 50000;

    internal static string ProcessKeyProvenance(ulong? managedKey, bool rawPair, bool matches) =>
        managedKey switch
        {
            null => "no-selected-managed-process",
            0 => "managed-key-zero",
            _ when !rawPair => "raw-pair-unavailable",
            _ when matches => "full-width-match",
            _ => "nonzero-key-mismatch"
        };

    internal static int CheckProcessKey()
    {
        const ulong key = 0xFFFF000000001234UL;
        var pair = new (int Kind, long Tick, ulong Key)[] { (3, 10, key), (4, 20, key) };
        if (ProcessKeyProvenance(null, true, false) != "no-selected-managed-process" ||
            ProcessKeyProvenance(0, true, false) != "managed-key-zero" ||
            ProcessKeyProvenance(key, false, false) != "raw-pair-unavailable" ||
            ProcessKeyProvenance(key, true, Boundaries.MatchesPairKey(pair, false, key)) != "full-width-match" ||
            ProcessKeyProvenance(0x1234, true, Boundaries.MatchesPairKey(pair, false, 0x1234)) != "nonzero-key-mismatch" ||
            Boundaries.MatchesPairKey(pair, true, key) ||
            Boundaries.MatchesPairKey(pair[..1], false, key))
            return 1;
        Console.WriteLine("COMPLETE gameplay process key diagnostics cases=7");
        return 0;
    }

    internal static string CreationProvenance(int models, bool hasValue, bool partial) => models switch
    {
        0 => "no-target-process-model",
        > 1 => "ambiguous-target-process-model",
        _ when !hasValue => "managed-creation-unavailable",
        _ when partial => "managed-creation-partial",
        _ => "managed-creation-full"
    };

    internal static int Check()
    {
        if (CreationProvenance(0, false, false) != "no-target-process-model" ||
            CreationProvenance(2, false, false) != "ambiguous-target-process-model" ||
            CreationProvenance(1, false, false) != "managed-creation-unavailable" ||
            CreationProvenance(1, true, true) != "managed-creation-partial" ||
            CreationProvenance(1, true, false) != "managed-creation-full" ||
            CreationMatches(null) || !CreationMatches(0) || !CreationMatches(50000) || CreationMatches(50001))
            return 1;
        Console.WriteLine("COMPLETE gameplay identity diagnostics cases=9");
        return 0;
    }
}

readonly record struct Window(long Start, long End, int FirstKind, int LastKind);

sealed class Boundaries(int pid, int tid)
{
    private static readonly Guid ProcessProvider = new("3d6fa8d0-fe05-11d0-9dda-00c04fd7ba7c");
    private static readonly Guid ThreadProvider = new("3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c");
    private readonly List<(int Kind, long Tick, ulong Key)> process = [];
    private readonly List<(int Kind, long Tick, ulong Key)> thread = [];
    private readonly List<BoundaryEvidence> processEvidence = [];
    private readonly List<BoundaryEvidence> threadEvidence = [];
    private bool invalid;

    public void Register(ITraceSource trace) => trace.Use(new[] { ProcessProvider, ThreadProvider }, context =>
    {
        var e = context.Event;
        if (!e.IsClassic) return;
        int opcode = e.AsClassicEvent.Id;
        if (opcode is < 1 or > 4) return;
        var data = e.Data;
        bool isProcess = e.ProviderId == ProcessProvider;
        int width = e.Is32Bit ? 4 : 8;
        if (isProcess ? e.Version is not (2 or 3 or 4) || data.Length < width + 4 :
                        e.Version is not (2 or 3 or 4) || data.Length < 8)
        {
            invalid = true;
            return;
        }
        if (BinaryPrimitives.ReadUInt32LittleEndian(isProcess ? data[width..] : data) != (uint)pid ||
            (!isProcess && BinaryPrimitives.ReadUInt32LittleEndian(data[4..]) != (uint)tid)) return;
        var list = isProcess ? process : thread;
        if (!e.Timestamp.HasValue || e.Timestamp.IsPartial || list.Count >= 8)
        {
            invalid = true;
            return;
        }
        ulong key = isProcess ? (width == 8 ? BinaryPrimitives.ReadUInt64LittleEndian(data) :
            BinaryPrimitives.ReadUInt32LittleEndian(data)) : (uint)tid;
        list.Add((opcode, e.Timestamp.Value.RawValue, key));
        (isProcess ? processEvidence : threadEvidence).Add(
            new(opcode, e.Timestamp.Value.RawValue, e.Version, width));
    });

    private Window Resolve(List<(int Kind, long Tick, ulong Key)> list)
    {
        return ResolvePair(list, invalid);
    }

    internal static Window ResolvePair(IReadOnlyList<(int Kind, long Tick, ulong Key)> list, bool invalid)
    {
        if (invalid || list.Count != 2) return default;
        var first = list[0];
        var last = list[1];
        return first.Kind is 1 or 3 && last.Kind is 2 or 4 && first.Tick < last.Tick
            && first.Key != 0 && first.Key == last.Key ? new(first.Tick, last.Tick, first.Kind, last.Kind) : default;
    }

    public Window ProcessWindow() => Resolve(process);
    public Window ThreadWindow() => Resolve(thread);
    internal record BoundaryEvidence(int Kind, long Tick, int Version, int PointerBytes);
    public IReadOnlyList<BoundaryEvidence> ProcessEvidence => processEvidence;
    public IReadOnlyList<BoundaryEvidence> ThreadEvidence => threadEvidence;
    internal static bool MatchesPairKey(IReadOnlyList<(int Kind, long Tick, ulong Key)> list, bool invalid, ulong key) =>
        ResolvePair(list, invalid) != default && list[0].Key == key;
    public bool ProcessKeyMatches(ulong key) => MatchesPairKey(process, invalid, key);

    internal static int Check()
    {
        var paired = new (int Kind, long Tick, ulong Key)[] { (3, 10, 4), (4, 100, 4) };
        var live = ResolvePair(paired, false);
        if (live != new Window(10, 100, 3, 4) ||
            ResolvePair([(1, 10, 4), (2, 100, 4)], false) != new Window(10, 100, 1, 2) ||
            ResolvePair([(3, 10, 4), (2, 100, 4)], false) != new Window(10, 100, 3, 2) ||
            ResolvePair([(3, 10, 4)], false) != default ||
            ResolvePair([(3, 10, 4), (4, 100, 5)], false) != default ||
            ResolvePair([(1, 10, 4), (2, 25, 4), (1, 50, 4), (2, 90, 4)], false) != default ||
            ResolvePair([(4, 10, 4), (3, 100, 4)], false) != default ||
            ResolvePair([(3, 10, 0), (4, 100, 0)], false) != default ||
            ResolvePair([(3, 100, 4), (4, 10, 4)], false) != default ||
            ResolvePair(paired, true) != default)
            return 1;
        Console.WriteLine("COMPLETE gameplay boundary predicates cases=10");
        return 0;
    }
}
