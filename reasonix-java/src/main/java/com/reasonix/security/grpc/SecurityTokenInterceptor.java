package com.reasonix.security.grpc;

import io.grpc.Context;
import io.grpc.Contexts;
import io.grpc.Metadata;
import io.grpc.ServerCall;
import io.grpc.ServerCallHandler;
import io.grpc.ServerInterceptor;
import io.grpc.Status;
import net.devh.boot.grpc.server.interceptor.GrpcGlobalServerInterceptor;
import org.springframework.beans.factory.annotation.Value;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Requires the per-launch desktop token on every security-service RPC. */
@GrpcGlobalServerInterceptor
public class SecurityTokenInterceptor implements ServerInterceptor {

    public static final String HEADER_NAME = "x-axiom-security-token";
    private static final Metadata.Key<String> TOKEN_KEY =
            Metadata.Key.of(HEADER_NAME, Metadata.ASCII_STRING_MARSHALLER);

    private final byte[] expectedToken;

    public SecurityTokenInterceptor(@Value("${axiom.security.token:}") String token) {
        this.expectedToken = token == null
                ? new byte[0]
                : token.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    public <ReqT, RespT> ServerCall.Listener<ReqT> interceptCall(
            ServerCall<ReqT, RespT> call,
            Metadata headers,
            ServerCallHandler<ReqT, RespT> next) {
        String supplied = headers.get(TOKEN_KEY);
        byte[] suppliedBytes = supplied == null
                ? new byte[0]
                : supplied.getBytes(StandardCharsets.UTF_8);
        if (expectedToken.length == 0
                || !MessageDigest.isEqual(expectedToken, suppliedBytes)) {
            call.close(
                    Status.UNAUTHENTICATED.withDescription(
                            "Missing or invalid Axiom security token"),
                    new Metadata());
            return new ServerCall.Listener<>() {};
        }
        return Contexts.interceptCall(Context.current(), call, headers, next);
    }
}
