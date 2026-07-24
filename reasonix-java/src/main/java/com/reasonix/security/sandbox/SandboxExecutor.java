package com.reasonix.security.sandbox;

import com.reasonix.security.grpc.SandboxExecuteRequest;
import com.reasonix.security.grpc.SandboxExecuteResponse;
import com.reasonix.security.sandbox.jna.WindowsSandbox;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

/**
 * Validates a command and executes it through the strongest available process guard.
 *
 * <p>This service does not misrepresent a shell blocklist as an OS filesystem
 * sandbox. Policies which cannot be guaranteed by the active backend fail closed.
 */
@Service
public class SandboxExecutor {

    private static final Logger log = LoggerFactory.getLogger(SandboxExecutor.class);
    private static final int MAX_COMMAND_LENGTH = 32_000;
    private static final int MAX_OUTPUT_BYTES = 2 * 1024 * 1024;
    private static final String STRICT_PROPERTY = "axiom.sandbox.strict";
    private static final String STRICT_ENVIRONMENT = "AXIOM_SANDBOX_STRICT";

    @Value("${axiom.sandbox.strict:false}")
    private boolean configuredStrict;

    private static final List<Pattern> BLOCKED_PATTERNS = List.of(
            Pattern.compile("(?i)\\brm\\s+(-rf\\s+)?[/\\\\]\\s*($|\\s|&&|\\|\\||;)"),
            Pattern.compile("(?i)\\bformat\\s+[c-z]:[/\\\\]?"),
            Pattern.compile("(?i)\\bdeltree\\s+[/\\\\]"),
            Pattern.compile("(?i)\\bdd\\s+if=/dev/(zero|random|urandom)"),
            Pattern.compile("(?i)\\bmkfs\\."),
            Pattern.compile("(?i)\\b(reboot|shutdown|halt|poweroff)\\b"),
            Pattern.compile("(?i)\\b(powershell|pwsh)(\\.exe)?\\s+"),
            Pattern.compile("(?i)\\b(wmic|wmic.exe)\\s+"),
            Pattern.compile("(?i)\\bnet\\s+(user|localgroup|share)\\s+"),
            Pattern.compile("(?i)\\breg\\s+(add|delete|import)\\s+"),
            Pattern.compile("(?i)\\bsc\\s+(create|delete|config)\\s+"),
            Pattern.compile("(?i)\\bdel\\s+/[fs]"),
            Pattern.compile("(?i)\\bcipher\\s+/w:"),
            Pattern.compile("(?i)\\battrib\\s+.*\\+.*s"),
            Pattern.compile("(?i)%\\s*comspec\\s*%"),
            Pattern.compile("(?i)(^|[;&|]\\s*)(cmd|sh|bash)\\s+.*[;&|]")
    );

    private static final List<Pattern> NETWORK_PATTERNS = List.of(
            Pattern.compile("(?i)\\b(curl|wget|ping|ssh|scp|sftp|ftp|telnet|nc|ncat)\\b"),
            Pattern.compile("(?i)\\bgit\\s+(clone|fetch|pull|push|ls-remote)\\b"),
            Pattern.compile("(?i)\\b(pip|pip3|npm|pnpm|yarn|cargo|go)\\s+"
                    + "(install|add|get|download|publish)\\b"),
            Pattern.compile("(?i)\\bcertutil(?:\\.exe)?\\b.*\\s-urlcache\\b"),
            Pattern.compile("(?i)\\bbitsadmin(?:\\.exe)?\\b.*\\s/transfer\\b"),
            Pattern.compile("(?i)\\b(mshta|rundll32)(?:\\.exe)?\\b.*https?://"),
            Pattern.compile("(?i)\\\\\\\\[^\\\\\\s]+\\\\")
    );

    public SandboxExecuteResponse execute(SandboxExecuteRequest request) {
        String command = request.getCommand();
        if (command == null || command.isBlank()) {
            return rejected("Command must not be empty");
        }
        if (command.length() > MAX_COMMAND_LENGTH) {
            return rejected("Command exceeds the sandbox length limit");
        }
        if (command.indexOf('\0') >= 0 || command.chars().anyMatch(
                value -> value < 0x20 && value != '\t' && value != '\r' && value != '\n')) {
            return rejected("Command contains unsupported control characters");
        }
        String inspectedCommand = command.replace("^", "").replace("`", "");
        if (matches(BLOCKED_PATTERNS, inspectedCommand)) {
            log.warn("Blocked command by security policy");
            return rejected("Command blocked by security policy");
        }
        if (!request.getNetwork() && matches(NETWORK_PATTERNS, inspectedCommand)) {
            log.warn("Blocked network-capable command while network access is disabled");
            return rejected("Network access is disabled by sandbox policy");
        }

        if (request.getForbidReadRootsCount() > 0) {
            return rejected(
                    "The active sandbox backend cannot guarantee forbidden read roots");
        }

        Path workingDirectory;
        try {
            workingDirectory = resolveWorkingDirectory(request.getWriteRootsList());
        } catch (IllegalArgumentException exception) {
            return rejected(exception.getMessage());
        }
        if (strictMode() && (!request.getNetwork() || request.getWriteRootsCount() > 0)) {
            return rejected(
                    "Strict sandbox policy requested, but this Java backend cannot "
                            + "guarantee network or filesystem isolation");
        }

        long timeout = Math.clamp(
                request.getTimeoutSeconds() == 0 ? 30 : request.getTimeoutSeconds(),
                1,
                300);
        if (isWindows()) {
            var result = new WindowsSandbox().execute(command, timeout, workingDirectory);
            String warning = policyWarning(request, result.warning());
            return SandboxExecuteResponse.newBuilder()
                    .setExitCode(result.exitCode())
                    .setStdout(nullToEmpty(result.stdout()))
                    .setStderr(appendWarning(result.stderr(), warning))
                    .build();
        }
        return executeUnix(command, timeout, workingDirectory);
    }

    private SandboxExecuteResponse executeUnix(
            String command,
            long timeout,
            Path workingDirectory) {
        Process process = null;
        try {
            var builder = new ProcessBuilder("sh", "-c", command)
                    .redirectErrorStream(false);
            if (workingDirectory != null) {
                builder.directory(workingDirectory.toFile());
            }
            sanitizeEnvironment(builder);
            process = builder.start();
            var stdout = drain(process.getInputStream());
            var stderr = drain(process.getErrorStream());
            boolean finished = process.waitFor(timeout, TimeUnit.SECONDS);
            if (!finished) {
                terminateTree(process);
                return SandboxExecuteResponse.newBuilder()
                        .setExitCode(-1)
                        .setStdout(output(stdout))
                        .setStderr("Timed out after " + timeout + "s")
                        .build();
            }
            return SandboxExecuteResponse.newBuilder()
                    .setStdout(output(stdout))
                    .setStderr(output(stderr))
                    .setExitCode(process.exitValue())
                    .build();
        } catch (Exception exception) {
            log.error("Guarded process execution failed: {}",
                    exception.getClass().getSimpleName());
            if (process != null) {
                terminateTree(process);
            }
            return rejected("Sandbox execution failed");
        }
    }

    private static Path resolveWorkingDirectory(List<String> writeRoots) {
        if (writeRoots.isEmpty()) {
            return null;
        }
        Path first = canonicalDirectory(writeRoots.getFirst());
        for (String root : writeRoots) {
            canonicalDirectory(root);
        }
        return first;
    }

    private static Path canonicalDirectory(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Write roots must not be empty");
        }
        try {
            Path path = Path.of(value).toAbsolutePath().normalize();
            if (!Files.isDirectory(path)) {
                throw new IllegalArgumentException("Write root must be an existing directory");
            }
            return path.toRealPath();
        } catch (IOException | RuntimeException exception) {
            throw new IllegalArgumentException("Invalid write root");
        }
    }

    private static boolean matches(List<Pattern> patterns, String command) {
        return patterns.stream().anyMatch(pattern -> pattern.matcher(command).find());
    }

    private boolean strictMode() {
        return configuredStrict
                || Boolean.parseBoolean(System.getProperty(STRICT_PROPERTY, "false"))
                || Boolean.parseBoolean(System.getenv(STRICT_ENVIRONMENT));
    }

    private static String policyWarning(
            SandboxExecuteRequest request,
            String backendWarning) {
        var warnings = new ArrayList<String>();
        if (backendWarning != null && !backendWarning.isBlank()) {
            warnings.add(backendWarning);
        }
        if (!request.getNetwork()) {
            warnings.add(
                    "network=false is enforced by command policy, not OS network isolation");
        }
        if (request.getWriteRootsCount() > 0) {
            warnings.add(
                    "write_roots selects the working directory but is not an OS filesystem boundary");
        }
        return String.join("; ", warnings);
    }

    private static String appendWarning(String stderr, String warning) {
        String output = nullToEmpty(stderr);
        if (warning == null || warning.isBlank()) {
            return output;
        }
        String prefix = output.isBlank() ? "" : output + System.lineSeparator();
        return prefix + "[sandbox warning] " + warning;
    }

    private static void sanitizeEnvironment(ProcessBuilder builder) {
        var environment = builder.environment();
        var sensitiveNames = new ArrayList<String>();
        for (String name : environment.keySet()) {
            String upper = name.toUpperCase(Locale.ROOT);
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
            } catch (IOException exception) {
                return "";
            }
        });
    }

    private static String output(CompletableFuture<String> future) {
        try {
            return future.get(5, TimeUnit.SECONDS);
        } catch (Exception exception) {
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

    private static SandboxExecuteResponse rejected(String message) {
        return SandboxExecuteResponse.newBuilder()
                .setExitCode(1)
                .setStderr(message)
                .build();
    }

    private static boolean isWindows() {
        return System.getProperty("os.name").toLowerCase(Locale.ROOT).contains("win");
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}
