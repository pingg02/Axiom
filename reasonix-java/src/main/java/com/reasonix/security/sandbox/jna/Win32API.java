package com.reasonix.security.sandbox.jna;

import com.sun.jna.Native;
import com.sun.jna.Pointer;
import com.sun.jna.Structure;
import com.sun.jna.ptr.IntByReference;
import com.sun.jna.ptr.PointerByReference;
import com.sun.jna.win32.StdCallLibrary;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.platform.win32.WinNT;

import java.util.Arrays;
import java.util.List;

/**
 * JNA 接口定义 — Windows 沙箱所需的 Win32 API。
 *
 * kernel32.dll: Job Object 进程管理
 * userenv.dll: AppContainer 配置文件
 * advapi32.dll: 安全令牌操作
 */
public interface Win32API extends StdCallLibrary {

    Win32API INSTANCE = Native.load("kernel32", Win32API.class);

    // ── Job Object (kernel32.dll) ────────────────────────────────────────

    Pointer CreateJobObjectW(Pointer lpJobAttributes, String lpName);

    boolean SetInformationJobObject(
            Pointer hJob,
            int JobObjectInfoType,   // JobObjectExtendedLimitInformation = 9
            Pointer lpJobObjectInfo,
            int cbJobObjectInfoLength
    );

    boolean AssignProcessToJobObject(Pointer hJob, Pointer hProcess);

    boolean TerminateJobObject(Pointer hJob, int uExitCode);

    Pointer OpenProcess(int dwDesiredAccess, boolean bInheritHandle, int dwProcessId);

    boolean CloseHandle(Pointer hObject);

    // ── Process creation ─────────────────────────────────────────────────

    boolean CreateProcessW(
            String lpApplicationName,
            String lpCommandLine,
            Pointer lpProcessAttributes,
            Pointer lpThreadAttributes,
            boolean bInheritHandles,
            int dwCreationFlags,
            Pointer lpEnvironment,
            String lpCurrentDirectory,
            Pointer lpStartupInfo,
            Pointer lpProcessInformation
    );

    // ── Token manipulation (advapi32.dll) ────────────────────────────────

    interface Advapi32 extends StdCallLibrary {
        Advapi32 INSTANCE = Native.load("advapi32", Advapi32.class);

        boolean DuplicateTokenEx(
                Pointer hExistingToken,
                int dwDesiredAccess,
                Pointer lpTokenAttributes,
                int ImpersonationLevel,
                int TokenType,
                PointerByReference phNewToken
        );

        boolean SetTokenInformation(
                Pointer TokenHandle,
                int TokenInformationClass,  // TokenIntegrityLevel = 25
                Pointer TokenInformation,
                int TokenInformationLength
        );

        boolean OpenProcessToken(
                Pointer ProcessHandle,
                int DesiredAccess,
                PointerByReference TokenHandle
        );

        boolean CreateProcessAsUserW(
                Pointer hToken,
                String lpApplicationName,
                String lpCommandLine,
                Pointer lpProcessAttributes,
                Pointer lpThreadAttributes,
                boolean bInheritHandles,
                int dwCreationFlags,
                Pointer lpEnvironment,
                String lpCurrentDirectory,
                Pointer lpStartupInfo,
                Pointer lpProcessInformation
        );
    }

    // ── AppContainer (userenv.dll) ───────────────────────────────────────

    interface Userenv extends StdCallLibrary {
        Userenv INSTANCE = Native.load("userenv", Userenv.class);

        int CreateAppContainerProfile(
                String pszAppContainerName,
                String pszDisplayName,
                String pszDescription,
                Pointer pCapabilities,
                int dwCapabilityCount,
                PointerByReference ppSid
        );

        int DeriveAppContainerSidFromAppContainerName(
                String pszAppContainerName,
                PointerByReference ppSid
        );

        int DeleteAppContainerProfile(String pszAppContainerName);

        int GetAppContainerFolderPath(
                String pszAppContainerName,
                IntByReference ppszPath
        );
    }

    // ── Structures ───────────────────────────────────────────────────────

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION extends Structure {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public long ProcessMemoryLimit;
        public long JobMemoryLimit;
        public long PeakProcessMemoryUsed;
        public long PeakJobMemoryUsed;

        @Override
        protected List<String> getFieldOrder() {
            return Arrays.asList(
                    "BasicLimitInformation", "IoInfo", "ProcessMemoryLimit",
                    "JobMemoryLimit", "PeakProcessMemoryUsed", "PeakJobMemoryUsed"
            );
        }
    }

    class JOBOBJECT_BASIC_LIMIT_INFORMATION extends Structure {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public int LimitFlags;
        public long MinimumWorkingSetSize;
        public long MaximumWorkingSetSize;
        public int ActiveProcessLimit;
        public long Affinity;
        public int PriorityClass;
        public int SchedulingClass;

        @Override
        protected List<String> getFieldOrder() {
            return Arrays.asList(
                    "PerProcessUserTimeLimit", "PerJobUserTimeLimit", "LimitFlags",
                    "MinimumWorkingSetSize", "MaximumWorkingSetSize", "ActiveProcessLimit",
                    "Affinity", "PriorityClass", "SchedulingClass"
            );
        }
    }

    class IO_COUNTERS extends Structure {
        public long ReadOperationCount;
        public long WriteOperationCount;
        public long OtherOperationCount;
        public long ReadTransferCount;
        public long WriteTransferCount;
        public long OtherTransferCount;

        @Override
        protected List<String> getFieldOrder() {
            return Arrays.asList(
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount"
            );
        }
    }

    class PROCESS_INFORMATION extends Structure {
        public Pointer hProcess;
        public Pointer hThread;
        public int dwProcessId;
        public int dwThreadId;

        @Override
        protected List<String> getFieldOrder() {
            return Arrays.asList("hProcess", "hThread", "dwProcessId", "dwThreadId");
        }
    }

    class STARTUPINFOW extends Structure {
        public int cb;
        public String lpReserved;
        public String lpDesktop;
        public String lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public Pointer lpReserved2;
        public Pointer hStdInput;
        public Pointer hStdOutput;
        public Pointer hStdError;

        public STARTUPINFOW() {
            cb = size();
        }

        @Override
        protected List<String> getFieldOrder() {
            return Arrays.asList(
                    "cb", "lpReserved", "lpDesktop", "lpTitle",
                    "dwX", "dwY", "dwXSize", "dwYSize",
                    "dwXCountChars", "dwYCountChars", "dwFillAttribute",
                    "dwFlags", "wShowWindow", "cbReserved2",
                    "lpReserved2", "hStdInput", "hStdOutput", "hStdError"
            );
        }
    }
}
