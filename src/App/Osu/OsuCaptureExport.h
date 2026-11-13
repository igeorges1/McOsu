#ifndef OSUCAPTUREEXPORT_H
#define OSUCAPTUREEXPORT_H

#include "OsuPerformanceHistory.h"
#include "OsuTimingAudioCapture.h"
#include <memory>

class OsuCaptureExport
{
public:
	struct Job
	{
		std::string source, map = "unknown", metadata;
		OsuTimingAudioCapture timing;
		bool hasTiming = false, timingComplete = false, hasPerformance = false;
		bool postClosed = false;
		const char *postEnd = "target";
		OsuPerformanceHistory::Window performance;
		double mark = 0, snapshotMS = 0, readbackMS = -1, frame = -1, frameEngine = -1;
		unsigned long long epoch = 0;
		unsigned width = 0, height = 0;
		std::vector<unsigned char> pixels;
		std::string screenshot; // Empty means disabled; pending never reaches the worker.
	};
	struct Result
	{
		std::string directory, error;
		bool timing = false, performance = false, screenshot = false;
		bool timingPartial = false;
	};

	OsuCaptureExport() = default;
	OsuCaptureExport(const OsuCaptureExport &) = delete;
	OsuCaptureExport &operator=(const OsuCaptureExport &) = delete;
	~OsuCaptureExport();
	bool busy() const { return m_handle != nullptr; }
	bool submit(std::unique_ptr<Job> job);
	bool poll(Result &result);
	void close();

private:
	struct Work;
#ifdef _WIN32
	static unsigned __stdcall run(void *argument);
#endif
	std::shared_ptr<Work> m_work;
	void *m_handle = nullptr;
};

#endif
