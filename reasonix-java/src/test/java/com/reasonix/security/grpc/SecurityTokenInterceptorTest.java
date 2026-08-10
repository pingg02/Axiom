package com.reasonix.security.grpc;

import io.grpc.Metadata;
import io.grpc.MethodDescriptor;
import io.grpc.ServerCall;
import io.grpc.Status;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SecurityTokenInterceptorTest {

    @Test
    void acceptsMatchingPerLaunchToken() {
        var interceptor = new SecurityTokenInterceptor("launch-token");
        var call = new RecordingCall();
        var listener = new ServerCall.Listener<String>() {};
        var nextCalled = new boolean[] {false};
        var headers = new Metadata();
        headers.put(
                Metadata.Key.of(
                        SecurityTokenInterceptor.HEADER_NAME,
                        Metadata.ASCII_STRING_MARSHALLER),
                "launch-token");

        var actual = interceptor.interceptCall(call, headers, (ignoredCall, ignoredHeaders) -> {
            nextCalled[0] = true;
            return listener;
        });

        assertNotNull(actual);
        assertTrue(nextCalled[0]);
        assertFalse(call.closed);
    }

    @Test
    void rejectsMissingToken() {
        var interceptor = new SecurityTokenInterceptor("launch-token");
        var call = new RecordingCall();
        var nextCalled = new boolean[] {false};

        interceptor.interceptCall(call, new Metadata(), (ignoredCall, ignoredHeaders) -> {
            nextCalled[0] = true;
            return new ServerCall.Listener<>() {};
        });

        assertTrue(call.closed);
        assertEquals(Status.Code.UNAUTHENTICATED, call.status.getCode());
        assertFalse(nextCalled[0]);
    }

    private static final class RecordingCall extends ServerCall<String, String> {
        private boolean closed;
        private Status status = Status.UNKNOWN;

        @Override
        public void request(int numMessages) {}

        @Override
        public void sendHeaders(Metadata headers) {}

        @Override
        public void sendMessage(String message) {}

        @Override
        public void close(Status nextStatus, Metadata trailers) {
            closed = true;
            status = nextStatus;
        }

        @Override
        public boolean isCancelled() {
            return false;
        }

        @Override
        public MethodDescriptor<String, String> getMethodDescriptor() {
            return null;
        }
    }
}
