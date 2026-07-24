package com.reasonix.security.sandbox;

import com.reasonix.security.grpc.SandboxExecuteRequest;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SandboxExecutorTest {

    private final SandboxExecutor executor = new SandboxExecutor();

    @Test
    void emptyCommandReturnsError() {
        var req = SandboxExecuteRequest.newBuilder().setCommand("").build();
        var resp = executor.execute(req);
        assertTrue(resp.getStderr().contains("empty") || resp.getExitCode() != 0);
    }

    @Test
    void echoCommandReturnsOutput() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("echo hello").setTimeoutSeconds(10).build();
        var resp = executor.execute(req);
        assertEquals(0, resp.getExitCode());
        assertTrue(resp.getStdout().contains("hello"),
                "Expected 'hello' in stdout: " + resp.getStdout());
    }

    @Test
    void rmRfRootIsBlocked() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("rm -rf /").setTimeoutSeconds(10).build();
        var resp = executor.execute(req);
        assertTrue(resp.getStderr().contains("blocked"),
                "Expected blocklist to reject 'rm -rf /': " + resp.getStderr());
    }

    @Test
    void powershellExeBlocked() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("powershell.exe -Command write-host test")
                .setTimeoutSeconds(10).build();
        var resp = executor.execute(req);
        assertTrue(resp.getStderr().contains("blocked"),
                "Expected powershell.exe blocked: " + resp.getStderr());
    }

    @Test
    void blocklistCaseInsensitive() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("POWERSHELL.EXE -Command test")
                .setTimeoutSeconds(10).build();
        var resp = executor.execute(req);
        assertTrue(resp.getStderr().contains("blocked"),
                "Expected case-insensitive block: " + resp.getStderr());
    }

    @Test
    void timeoutReturnsError() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("ping 127.0.0.1")
                .setTimeoutSeconds(1).build();
        var resp = executor.execute(req);
        assertTrue(resp.getStderr().contains("Timed") || resp.getExitCode() != 0,
                "Expected timeout: " + resp.getStderr());
    }

    @Test
    void forbiddenReadRootsFailClosed() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("echo should-not-run")
                .addForbidReadRoots(System.getProperty("user.home"))
                .build();
        var resp = executor.execute(req);
        assertNotEquals(0, resp.getExitCode());
        assertTrue(resp.getStderr().contains("cannot guarantee"));
        assertFalse(resp.getStdout().contains("should-not-run"));
    }

    @Test
    void networkCommandIsBlockedWhenNetworkDisabled() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("curl https://example.com")
                .setNetwork(false)
                .build();
        var resp = executor.execute(req);
        assertNotEquals(0, resp.getExitCode());
        assertTrue(resp.getStderr().contains("Network access is disabled"));
        assertFalse(resp.getStderr().contains("https://example.com"));
    }

    @Test
    void blockedCommandIsNotReflectedIntoError() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("powershell.exe -Command write-host super-secret-value")
                .build();
        var resp = executor.execute(req);
        assertNotEquals(0, resp.getExitCode());
        assertFalse(resp.getStderr().contains("super-secret-value"));
    }

    @Test
    void invalidWriteRootFailsClosed() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("echo should-not-run")
                .addWriteRoots("Z:\\path-that-does-not-exist")
                .build();
        var resp = executor.execute(req);
        assertNotEquals(0, resp.getExitCode());
        assertTrue(resp.getStderr().contains("Invalid write root")
                || resp.getStderr().contains("existing directory"));
    }

    @Test
    void caretObfuscatedPowerShellIsBlocked() {
        var req = SandboxExecuteRequest.newBuilder()
                .setCommand("power^shell.exe -Command write-host hidden")
                .setNetwork(true)
                .build();
        var resp = executor.execute(req);
        assertNotEquals(0, resp.getExitCode());
        assertTrue(resp.getStderr().contains("blocked"));
        assertFalse(resp.getStderr().contains("hidden"));
    }

    @Test
    void strictModeFailsClosedForUnenforceablePolicies() {
        String previous = System.getProperty("axiom.sandbox.strict");
        try {
            System.setProperty("axiom.sandbox.strict", "true");
            var req = SandboxExecuteRequest.newBuilder()
                    .setCommand("echo should-not-run")
                    .setNetwork(false)
                    .build();
            var resp = executor.execute(req);
            assertNotEquals(0, resp.getExitCode());
            assertTrue(resp.getStderr().contains("cannot guarantee"));
            assertFalse(resp.getStdout().contains("should-not-run"));
        } finally {
            if (previous == null) {
                System.clearProperty("axiom.sandbox.strict");
            } else {
                System.setProperty("axiom.sandbox.strict", previous);
            }
        }
    }
}
