package com.reasonix.security.grpc;

import com.reasonix.security.guardian.GuardianService;
import com.reasonix.security.permission.PermissionGate;
import com.reasonix.security.secrets.SecretsRedactor;
import com.reasonix.security.sandbox.SandboxExecutor;
import io.grpc.stub.StreamObserver;
import net.devh.boot.grpc.server.service.GrpcService;
import org.springframework.beans.factory.annotation.Autowired;

@GrpcService
public class SecurityGrpcService extends SecurityServiceGrpc.SecurityServiceImplBase {

    @Autowired private PermissionGate permissionGate;
    @Autowired private GuardianService guardianService;
    @Autowired private SecretsRedactor secretsRedactor;
    @Autowired private SandboxExecutor sandboxExecutor;

    @Override
    public void checkPermission(PermissionCheckRequest req,
                                StreamObserver<PermissionCheckResponse> responseObserver) {
        var decision = permissionGate.decide(req.getToolName(), req.getReadOnly(), req.getArgsJson());
        var resp = PermissionCheckResponse.newBuilder()
                .setDecision(mapDecision(decision))
                .build();
        responseObserver.onNext(resp);
        responseObserver.onCompleted();
    }

    @Override
    public void reviewTool(GuardianReviewRequest req,
                           StreamObserver<GuardianVerdict> responseObserver) {
        var verdict = guardianService.review(
                req.getToolName(), req.getArgsJson(), req.getTranscriptDelta(), req.getSessionId());
        responseObserver.onNext(verdict);
        responseObserver.onCompleted();
    }

    @Override
    public void redactSecrets(RedactRequest req,
                              StreamObserver<RedactResponse> responseObserver) {
        var redacted = secretsRedactor.redact(req.getText(), req.getRedactToolOutput());
        var resp = RedactResponse.newBuilder().setRedactedText(redacted).build();
        responseObserver.onNext(resp);
        responseObserver.onCompleted();
    }

    @Override
    public void executeSandboxed(SandboxExecuteRequest req,
                                 StreamObserver<SandboxExecuteResponse> responseObserver) {
        var result = sandboxExecutor.execute(req);
        responseObserver.onNext(result);
        responseObserver.onCompleted();
    }

    private PermissionCheckResponse.Decision mapDecision(PermissionGate.Decision decision) {
        return switch (decision) {
            case ALLOW -> PermissionCheckResponse.Decision.ALLOW;
            case ASK -> PermissionCheckResponse.Decision.ASK;
            case DENY -> PermissionCheckResponse.Decision.DENY;
        };
    }
}
