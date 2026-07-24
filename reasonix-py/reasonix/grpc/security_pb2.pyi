from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PermissionCheckRequest(_message.Message):
    __slots__ = ("tool_name", "args_json", "read_only")
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_JSON_FIELD_NUMBER: _ClassVar[int]
    READ_ONLY_FIELD_NUMBER: _ClassVar[int]
    tool_name: str
    args_json: str
    read_only: bool
    def __init__(self, tool_name: _Optional[str] = ..., args_json: _Optional[str] = ..., read_only: _Optional[bool] = ...) -> None: ...

class PermissionCheckResponse(_message.Message):
    __slots__ = ("decision", "reason")
    class Decision(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        ALLOW: _ClassVar[PermissionCheckResponse.Decision]
        ASK: _ClassVar[PermissionCheckResponse.Decision]
        DENY: _ClassVar[PermissionCheckResponse.Decision]
    ALLOW: PermissionCheckResponse.Decision
    ASK: PermissionCheckResponse.Decision
    DENY: PermissionCheckResponse.Decision
    DECISION_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    decision: PermissionCheckResponse.Decision
    reason: str
    def __init__(self, decision: _Optional[_Union[PermissionCheckResponse.Decision, str]] = ..., reason: _Optional[str] = ...) -> None: ...

class GuardianReviewRequest(_message.Message):
    __slots__ = ("tool_name", "args_json", "transcript_delta", "session_id")
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_JSON_FIELD_NUMBER: _ClassVar[int]
    TRANSCRIPT_DELTA_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    tool_name: str
    args_json: str
    transcript_delta: str
    session_id: str
    def __init__(self, tool_name: _Optional[str] = ..., args_json: _Optional[str] = ..., transcript_delta: _Optional[str] = ..., session_id: _Optional[str] = ...) -> None: ...

class GuardianVerdict(_message.Message):
    __slots__ = ("risk_level", "outcome", "rationale", "user_authorization", "breaker_tripped", "breaker_reason")
    RISK_LEVEL_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    RATIONALE_FIELD_NUMBER: _ClassVar[int]
    USER_AUTHORIZATION_FIELD_NUMBER: _ClassVar[int]
    BREAKER_TRIPPED_FIELD_NUMBER: _ClassVar[int]
    BREAKER_REASON_FIELD_NUMBER: _ClassVar[int]
    risk_level: str
    outcome: str
    rationale: str
    user_authorization: str
    breaker_tripped: bool
    breaker_reason: str
    def __init__(self, risk_level: _Optional[str] = ..., outcome: _Optional[str] = ..., rationale: _Optional[str] = ..., user_authorization: _Optional[str] = ..., breaker_tripped: _Optional[bool] = ..., breaker_reason: _Optional[str] = ...) -> None: ...

class RedactRequest(_message.Message):
    __slots__ = ("text", "redact_tool_output")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    REDACT_TOOL_OUTPUT_FIELD_NUMBER: _ClassVar[int]
    text: str
    redact_tool_output: bool
    def __init__(self, text: _Optional[str] = ..., redact_tool_output: _Optional[bool] = ...) -> None: ...

class RedactResponse(_message.Message):
    __slots__ = ("redacted_text",)
    REDACTED_TEXT_FIELD_NUMBER: _ClassVar[int]
    redacted_text: str
    def __init__(self, redacted_text: _Optional[str] = ...) -> None: ...

class SandboxExecuteRequest(_message.Message):
    __slots__ = ("command", "write_roots", "forbid_read_roots", "network", "timeout_seconds")
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    WRITE_ROOTS_FIELD_NUMBER: _ClassVar[int]
    FORBID_READ_ROOTS_FIELD_NUMBER: _ClassVar[int]
    NETWORK_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    command: str
    write_roots: _containers.RepeatedScalarFieldContainer[str]
    forbid_read_roots: _containers.RepeatedScalarFieldContainer[str]
    network: bool
    timeout_seconds: int
    def __init__(self, command: _Optional[str] = ..., write_roots: _Optional[_Iterable[str]] = ..., forbid_read_roots: _Optional[_Iterable[str]] = ..., network: _Optional[bool] = ..., timeout_seconds: _Optional[int] = ...) -> None: ...

class SandboxExecuteResponse(_message.Message):
    __slots__ = ("stdout", "stderr", "exit_code")
    STDOUT_FIELD_NUMBER: _ClassVar[int]
    STDERR_FIELD_NUMBER: _ClassVar[int]
    EXIT_CODE_FIELD_NUMBER: _ClassVar[int]
    stdout: str
    stderr: str
    exit_code: int
    def __init__(self, stdout: _Optional[str] = ..., stderr: _Optional[str] = ..., exit_code: _Optional[int] = ...) -> None: ...
