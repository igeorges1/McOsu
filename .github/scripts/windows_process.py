"""Bounded direct-child execution; Windows jobs own descendants, never names/PIDs."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def nonmodal():
    if os.name == "nt":
        ctypes.windll.kernel32.SetErrorMode(1 | 2 | 0x8000)


class WindowsJob:
    def __init__(self):
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (pointer-size aware).
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                        ("max_working", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def start(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        resume = ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = ctypes.c_long
        if resume(int(process._handle)) != 0:
            raise OSError("Cannot resume owned suspended child")

    def close(self):
        if self.handle:
            self.api.TerminateJobObject(self.handle, 124)
            self.api.CloseHandle(self.handle)
            self.handle = None


def execute(argv, cwd, env, seconds, stdout, stderr):
    """Return actual child status, preserving logs even on launch/setup failure."""
    nonmodal()
    record = {"argv": [str(a) for a in argv], "cwd": str(cwd), "deadline_seconds": seconds,
              "stdout": str(stdout), "stderr": str(stderr), "pid": None, "exit": None,
              "exit_hex": None, "timeout": False, "error": None, "owned_process_remaining": False,
              "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "executable_sha256": digest(argv[0]) if Path(argv[0]).is_file() else None}
    started = time.monotonic()
    process = job = None
    try:
        with open(stdout, "wb") as out, open(stderr, "wb") as err:
            job = WindowsJob() if os.name == "nt" else None
            process = subprocess.Popen(record["argv"], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=err,
                                       creationflags=0x4 if job else 0,
                                       start_new_session=not bool(job))
            record["pid"] = process.pid
            if job:
                job.start(process)
            try:
                process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                record["timeout"] = True
    except OSError as error:
        record["error"] = str(error)
    except KeyboardInterrupt:
        record["error"] = "Controller interrupted"
    finally:
        if job:
            job.close()  # also removes descendants after normal direct-child exit
        elif process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            record["exit"] = process.returncode
            record["exit_hex"] = "0x%08X" % (process.returncode & 0xffffffff)
            record["owned_process_remaining"] = process.poll() is None
        record["seconds"] = round(time.monotonic() - started, 3)
        record["ended_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return record
