#include "OsuCaptureExport.h"
#include "lodepng.h"
#include <chrono>
#include <cstdio>
#include <ctime>
#include <fstream>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <process.h>
#endif

bool OsuGameplayCapture::supported()
{
#ifdef _WIN32
	return true;
#else
	return false;
#endif
}

OsuGameplayCapture::Identity OsuGameplayCapture::identify()
{
	Identity result;
#ifdef _WIN32
	FILETIME creation, exit, kernel, user;
	LARGE_INTEGER frequency;
	if (GetProcessTimes(GetCurrentProcess(), &creation, &exit, &kernel, &user)
		&& QueryPerformanceFrequency(&frequency))
	{
		result.creation = (std::uint64_t(creation.dwHighDateTime) << 32) | creation.dwLowDateTime;
		result.frequency = frequency.QuadPart;
		result.pid = GetCurrentProcessId();
		result.tid = GetCurrentThreadId();
	}
#endif
	return result;
}

unsigned OsuGameplayCapture::thread()
{
#ifdef _WIN32
	return GetCurrentThreadId();
#else
	return 0;
#endif
}

std::int64_t OsuGameplayCapture::ticks()
{
#ifdef _WIN32
	LARGE_INTEGER value;
	if (QueryPerformanceCounter(&value) && value.QuadPart >= 0) return value.QuadPart;
#endif
	return -1;
}

namespace
{
	using Clock = std::chrono::steady_clock;
	double ms(Clock::time_point start)
	{
		return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
	}

#ifdef _WIN32
	std::string reserveDirectory(unsigned limit)
	{
		const char *root = "timing-captures";
		if (!CreateDirectoryA(root, nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return {};
		const DWORD attributes = GetFileAttributesA(root);
		if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY)
			|| (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) return {};
		WIN32_FIND_DATAA entry{};
		const auto search = FindFirstFileA("timing-captures/*", &entry);
		unsigned count = 0;
		if (search != INVALID_HANDLE_VALUE)
		{
			do
			{
				const std::string name = entry.cFileName;
				if ((entry.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && name != "." && name != "..") ++count;
			}
			while (count < limit && FindNextFileA(search, &entry));
			const DWORD error = count < limit ? GetLastError() : ERROR_SUCCESS;
			FindClose(search);
			if (error != ERROR_SUCCESS && error != ERROR_NO_MORE_FILES) return {};
		}
		else if (GetLastError() != ERROR_FILE_NOT_FOUND) return {};
		if (count >= limit) return {};
		const auto stamp = static_cast<long long>(std::time(nullptr));
		for (int suffix = 0; suffix < 12; ++suffix)
		{
			char path[80];
			std::snprintf(path, sizeof(path), "timing-captures/mark-%lld-%02d", stamp, suffix);
			if (CreateDirectoryA(path, nullptr)) return path;
			if (GetLastError() != ERROR_ALREADY_EXISTS) break;
		}
		return {};
	}

	template <typename Write>
	bool publish(const std::string &directory, const char *name, Write write)
	{
		const std::string final = directory + '/' + name;
		const std::string temporary = final + ".partial";
		std::ofstream output(temporary, std::ios::binary);
		const bool written = output && write(output);
		output.close();
		return written && output && MoveFileA(temporary.c_str(), final.c_str());
	}

	bool saveGameplay(const OsuCaptureExport::Job &job, std::ostream &out, bool &partial)
	{
		const auto &mark = job.gameplay;
		const auto &window = job.performance;
		const auto &rows = window.rawFrames;
		const auto boundary = std::find_if(rows.begin(), rows.end(), [&](const OsuPerformanceHistory::Frame &row) {
			return row.sequence == window.rawBoundary;
		});
		const auto count = std::min(rows.size(), static_cast<std::size_t>(
			mark.config.valid() ? mark.config.rowLimit : OsuGameplayCapture::MAX_ROWS));
		std::size_t begin = rows.size() - count;
		if (boundary != rows.end()) begin = std::min(begin, static_cast<std::size_t>(boundary - rows.begin()));
		partial = !window.rawBoundary || window.rawPostCount < window.postTarget || count != rows.size();
		out.imbue(std::locale::classic());
		out << "MCOSU_GAMEPLAY_QPC 1\nsource " << job.source << "\nmap " << job.map
			<< "\nidentity " << mark.identity.pid << ' ' << mark.identity.creation << ' ' << mark.identity.tid
			<< ' ' << mark.identity.frequency << "\nmark " << mark.id << ' ' << mark.epoch << ' ' << mark.tick
			<< ' ' << window.rawBoundary << "\nsettings " << mark.config.requested << ' ' << mark.config.update
			<< ' ' << mark.config.draws << ' ' << mark.config.stages << ' ' << mark.config.drawLimit << ' '
			<< mark.config.rowLimit << ' ' << mark.historyRequested << ' ' << mark.history << ' '
			<< mark.tailRequested << ' ' << mark.tail << ' ' << mark.tailMilliseconds << ' ' << job.folderLimit
			<< ' ' << mark.screenshot << ' ' << mark.model
			<< "\nstatus " << mark.status << "\npost_end " << job.postEnd
			<< "\ncounts " << rows.size() << ' ' << count << ' ' << window.evicted << ' ' << window.rawPostCount
			<< "\nstages " << mark.snapshotEnd << ' ' << mark.readback.start << ' ' << mark.readback.end << '\n';
		for (std::size_t i = begin; i < begin + count; ++i)
		{
			const auto &row = rows[i];
			const auto &raw = row.raw;
			out << "frame " << row.sequence << ' ' << raw.epoch << ' ' << raw.update.start << ' ' << raw.next
				<< ' ' << raw.update.end << ' ' << row.draws << ' ' << raw.observed << ' ' << row.context;
			for (const auto &span : raw.draws) out << ' ' << span.start << ' ' << span.end;
			out << '\n';
			auto phaseEnd = mark.config.update ? raw.update.end : raw.update.start;
			for (unsigned draw = 0; mark.config.draws && draw < std::min(raw.observed, static_cast<unsigned>(mark.config.drawLimit)); ++draw)
			{
				const auto &span = raw.draws[draw];
				partial = partial || span.start < phaseEnd || span.start < raw.update.start
					|| span.end < span.start || span.end > raw.next;
				phaseEnd = span.end;
			}
			partial = partial || raw.next <= raw.update.start
				|| (mark.config.update && (raw.update.end < raw.update.start || raw.update.end > raw.next))
				|| (mark.config.draws && (raw.observed != row.draws || raw.observed > static_cast<unsigned>(mark.config.drawLimit)));
		}
		out << "end " << (partial ? "partial" : "complete") << '\n';
		return out.good();
	}

	void save(const OsuCaptureExport::Job &job, OsuCaptureExport::Result &result)
	{
		const auto reserveStart = Clock::now();
		result.directory = reserveDirectory(job.folderLimit);
		const double reserveMS = ms(reserveStart);
		if (result.directory.empty())
		{
			result.error = "Cannot reserve timing capture folder (quota or storage error).";
			return;
		}
		const auto &directory = result.directory;
		double reportMS = -1, encodeMS = -1, imageWriteMS = -1, perfMS = -1;
		if (job.hasTiming)
		{
			const auto start = Clock::now();
			result.timing = publish(directory, "capture.mct", [&](std::ostream &out) {
				return job.timing.write(out, job.source, job.map, job.metadata);
			});
			reportMS = ms(start);
			result.timingPartial = result.timing && !job.timingComplete;
		}
		if (!job.screenshot.empty())
		{
			const char *status = job.screenshot.c_str();
			if (!job.pixels.empty())
			{
				auto start = Clock::now();
				std::vector<unsigned char> png;
				const unsigned error = lodepng::encode(png, job.pixels, job.width, job.height, LCT_RGB, 8);
				encodeMS = ms(start);
				status = "PNG encoding failed";
				if (!error)
				{
					start = Clock::now();
					result.screenshot = publish(directory, "frame.png", [&](std::ostream &out) {
						out.write(reinterpret_cast<const char *>(png.data()), png.size());
						return out.good();
					});
					imageWriteMS = ms(start);
					status = result.screenshot ? "saved" : "PNG write failed";
				}
			}
			const bool receipt = publish(directory, "screenshot.txt", [&](std::ostream &out) {
				out.imbue(std::locale::classic());
				out << std::setprecision(17) << "frame_real_seconds=" << job.frame << "\nframe_engine_seconds=" << job.frameEngine
					<< "\ntiming_epoch=" << job.epoch << "\nstatus=" << status << "\nwidth=" << job.width
					<< "\nheight=" << job.height << '\n';
				return out.good();
			});
			if (!receipt) result.screenshot = false;
		}
		if (job.hasPerformance)
		{
			const auto start = Clock::now();
			result.performance = publish(directory, "performance.csv", [&](std::ostream &out) {
				out.imbue(std::locale::classic());
				out << std::setprecision(17)
					<< "MCOSU_PERFORMANCE 1\nsource " << job.source << "\nmap " << job.map
					<< "\nclock engine_monotonic_seconds\nmark " << job.mark
					<< "\nevicted " << job.performance.evicted << "\ndiscontinuities " << job.performance.discontinuities
					<< "\npost " << job.performance.postCount << ' ' << job.performance.postTarget
					<< "\nboundary " << job.performance.boundarySequence
					<< "\npost_end " << job.postEnd
					<< "\nstages_ms " << job.snapshotMS << ' ' << job.readbackMS << ' ' << reserveMS
					<< ' ' << reportMS << ' ' << encodeMS << ' ' << imageWriteMS
					<< "\nframes " << job.performance.frames.size()
					<< "\nsequence,start,interval,update,draw,draws,context,fps_limit,background_limit,unlimited,vsync\n";
				for (const auto &frame : job.performance.frames)
					out << frame.sequence << ',' << frame.start << ',' << frame.interval << ',' << frame.update << ','
						<< frame.draw << ',' << frame.draws << ',' << frame.context << ',' << frame.foregroundLimit
						<< ',' << frame.backgroundLimit << ',' << frame.unlimited << ',' << frame.vsync << '\n';
				out << "end\n";
				return out.good();
			});
			perfMS = ms(start);
		}
		if (job.gameplay.config.requested)
			result.gameplay = publish(directory, "gameplay.qpc", [&](std::ostream &out) {
				return saveGameplay(job, out, result.gameplayPartial);
			});
		const bool receipt = publish(directory, "export.txt", [&](std::ostream &out) {
			out.imbue(std::locale::classic());
			out << std::setprecision(17) << "mark_real_seconds=" << job.mark << "\nsnapshot_main_ms=" << job.snapshotMS
				<< "\nreadback_main_ms=" << job.readbackMS << "\nreserve_worker_ms=" << reserveMS
				<< "\ntiming_format_and_write_worker_ms=" << reportMS
				<< "\npng_encode_worker_ms=" << encodeMS << "\npng_write_worker_ms=" << imageWriteMS
				<< "\nperformance_format_and_write_worker_ms=" << perfMS
				<< "\ntiming=" << (!job.hasTiming ? "disabled" : !result.timing ? "failed" : job.timingComplete ? "saved" : "partial")
				<< "\nperformance=" << (!job.hasPerformance ? "disabled" : result.performance ? "saved" : "failed")
				<< "\ngameplay_qpc=" << (!job.gameplay.config.requested ? "disabled" : !result.gameplay ? "failed" : result.gameplayPartial ? "partial" : "saved")
				<< "\nscreenshot=" << (job.screenshot.empty() ? "disabled" : result.screenshot ? "saved" : "unavailable") << '\n';
			return out.good();
		});
		if (!receipt || (job.hasTiming && !result.timing) || (job.hasPerformance && !result.performance)
			|| (!job.screenshot.empty() && !result.screenshot) || (job.gameplay.config.requested && !result.gameplay))
			result.error = "One or more capture components could not be saved.";
	}
#endif
}

struct OsuCaptureExport::Work
{
	std::unique_ptr<Job> job;
	Result result;
};

OsuCaptureExport::~OsuCaptureExport() { close(); }

#ifdef _WIN32
unsigned __stdcall OsuCaptureExport::run(void *argument)
{
	std::unique_ptr<std::shared_ptr<Work>> owned(static_cast<std::shared_ptr<Work> *>(argument));
	auto &work = **owned;
	try { save(*work.job, work.result); }
	catch (...) { work.result.error = "Capture export failed."; }
	work.job.reset();
	return 0;
}
#endif

bool OsuCaptureExport::submit(std::unique_ptr<Job> job)
{
#ifdef _WIN32
	if (busy() || !job) return false;
	auto work = std::make_shared<Work>();
	work->job = std::move(job);
	auto *argument = new std::shared_ptr<Work>(work);
	const auto handle = reinterpret_cast<HANDLE>(_beginthreadex(nullptr, 0, run, argument, 0, nullptr));
	if (!handle)
	{
		delete argument;
		return false;
	}
	m_handle = handle;
	m_work = std::move(work);
	return true;
#else
	return false;
#endif
}

bool OsuCaptureExport::poll(Result &result)
{
#ifdef _WIN32
	if (!busy() || WaitForSingleObject(m_handle, 0) != WAIT_OBJECT_0) return false;
	result = std::move(m_work->result);
	CloseHandle(m_handle);
	m_handle = nullptr;
	m_work.reset();
	return true;
#else
	return false;
#endif
}

void OsuCaptureExport::close()
{
#ifdef _WIN32
	if (!busy()) return;
	WaitForSingleObject(m_handle, 100);
	CloseHandle(m_handle);
	m_handle = nullptr;
	m_work.reset();
#endif
}
