package com.reasonix.security.sandbox.jna;

import com.sun.jna.Pointer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * Guarded Windows process runner.
 *
 * <p>The child is attached to a Windows Job Object configured to terminate the
 * entire process tree when the job closes. AppContainer filesystem/network
 * isolation is deliberately not claimed here; callers must fail closed for
 * policies this runner cannot enforce.
 */
public final class WindowsSandbox {

    private static final Logger log = LoggerFactory.getLogger(WindowsSandbox.class);
    private static final int MAX_OUTPUT_BYTES = 2 * 1024 * 1024;
    private static final int JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9;
    private static final int JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008;
    private static final int JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100;
    private static final int JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private static final int PROCESS_TERMINATE = 0x0001;
    private static final int PROCESS_SET_QUOTA = 0x0100;
    private static final int PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
    private static final long PROCESS_MEMORY_LIMIT = 768L * 1024L * 1024L;

    public SandboxResult execute(String command, long timeoutSeconds, Path workingDirectory) {
        if (command == null || command.isBlank()) {
            return new SandboxResult("", "Command must not be empty", -1, "");
        }
        long timeout = Math.clamp(timeoutSeconds, 1, 300);
        Pointer job = null;
        Process process = null;
        String warning = "";

        try {
            var builder = new ProcessBuilder("cmd.exe", "/d", "/s", "/c", command)
                    .redirectErrorStream(false);
            if (workingDirectory != null) {
                builder.directory(workingDirectory.toFile());
            }
            sanitizeEnvironment(builder);
            process = builder.start();
            try {
                job = attachJobObject(process.pid());
            } catch (IllegalStateException exception) {
                // A host process may already live in a non-breakaway Job Object.
                // ProcessHandle cleanup still gives us deterministic timeout/cancel
                // behavior, while explicit filesystem policies remain fail-closed
                // in SandboxExecutor.
                log.warn("Windows Job Object unavailable; using process-tree guard");
                warning = "Windows Job Object unavailable; using process-tree guard";
            }

            var stdoutFuture = drain(process.getInputStream());
            var stderrFuture = drain(process.getErrorStream());
            boolean finished = process.waitFor(timeout, TimeUnit.SECONDS);
            if (!finished) {
                terminateTree(process);
                return new SandboxResult(
                        output(stdoutFuture),
                        "Timed out after " + timeout + "s",
                        -1,
                        warning);
            }

            return new SandboxResult(
                    output(stdoutFuture),
                    output(stderrFuture),
                    process.exitValue(),
                    warning);
        } catch (Exception e) {
            log.error("Windows guarded process execution failed: {}", e.getClass().getSimpleName());
            if (process != null) {
                terminateTree(process);
            }
            return new SandboxResult("", "Sandbox execution failed", 1, warning);
        } finally {
            if (job != null) {
                Win32API.INSTANCE.CloseHandle(job);
            }
        }
    }

    private Pointer attachJobObject(long pid) {
        Pointer job = Win32API.INSTANCE.CreateJobObjectW(Pointer.NULL, null);
        if (job == null || Pointer.nativeValue(job) == 0) {
            throw new IllegalStateException("CreateJobObjectW failed");
        }

        var info = new Win32API.JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation = new Win32API.JOBOBJECT_BASIC_LIMIT_INFORMATION();
        info.IoInfo = new Win32API.IO_COUNTERS();
        info.BasicLimitInformation.LimitFlags =
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                        | JOB_OBJECT_LIMIT_PROCESS_MEMORY;
        info.BasicLimitInformation.ActiveProcessLimit = 64;
        info.ProcessMemoryLimit = PROCESS_MEMORY_LIMIT;
        info.write();
        if (!Win32API.INSTANCE.SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                info.getPointer(),
                info.size())) {
            Win32API.INSTANCE.CloseHandle(job);
            throw new IllegalStateException("SetInformationJobObject failed");
        }

        Pointer processHandle = Win32API.INSTANCE.OpenProcess(
                PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_QUERY_LIMITED_INFORMATION,
                false,
                (int) pid);
        if (processHandle == null || Pointer.nativeValue(processHandle) == 0) {
            Win32API.INSTANCE.CloseHandle(job);
            throw new IllegalStateException("OpenProcess failed");
        }
        try {
            if (!Win32API.INSTANCE.AssignProcessToJobObject(job, processHandle)) {
                Win32API.INSTANCE.CloseHandle(job);
                throw new IllegalStateException("AssignProcessToJobObject failed");
            }
        } finally {
            Win32API.INSTANCE.CloseHandle(processHandle);
        }
        return job;
    }

    private static void sanitizeEnvironment(ProcessBuilder builder) {
        var environment = builder.environment();
        var sensitiveNames = new ArrayList<String>();
        for (var name : environment.keySet()) {
            var upper = name.toUpperCase(Locale.ROOT);
            if (upper.contains("TOKEN")
                    || upper.contains("SECRET")
                    || upper.contains("PASSWORD")
                    || upper.contains("API_KEY")
                    || upper.endsWith("_KEY")) {
                sensitiveNames.add(name);
            }
        }
        sensitiveNames.forEach(environment::remove);
    }

    private static CompletableFuture<String> drain(InputStream stream) {
        return CompletableFuture.supplyAsync(() -> {
            try (stream) {
                var captured = new ByteArrayOutputStream(MAX_OUTPUT_BYTES);
                byte[] buffer = new byte[8192];
                int retained = 0;
                boolean truncated = false;
                int read;
                while ((read = stream.read(buffer)) != -1) {
                    int writable = Math.min(read, MAX_OUTPUT_BYTES - retained);
                    if (writable > 0) {
                        captured.write(buffer, 0, writable);
                        retained += writable;
                    }
                    if (writable < read) {
                        truncated = true;
                    }
                }
                String text = captured.toString(StandardCharsets.UTF_8);
                return truncated ? text + System.lineSeparator() + "[output truncated]" : text;
            } catch (IOException e) {
                return "";
            }
        });
    }

    private static String output(CompletableFuture<String> future) {
        try {
            return future.get(5, TimeUnit.SECONDS);
        } catch (Exception e) {
            return "";
        }
    }

    private static void terminateTree(Process process) {
        List<ProcessHandle> descendants = process.descendants().toList();
        for (int index = descendants.size() - 1; index >= 0; index--) {
            descendants.get(index).destroyForcibly();
        }
        process.destroyForcibly();
    }

    public record SandboxResult(
            String stdout,
            String stderr,
            int exitCode,
            String warning) {}
}
