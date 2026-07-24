package com.reasonix.security;

import com.reasonix.security.secrets.SecretsRedactor;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SecretsRedactorTest {

    private final SecretsRedactor redactor = new SecretsRedactor();

    @Test
    void maskShortValue() {
        assertEquals("[redacted]", SecretsRedactor.mask("abc"));
    }

    @Test
    void maskOpenAIKey() {
        String result = SecretsRedactor.mask("sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz");
        assertTrue(result.startsWith("sk-"));
        assertTrue(result.contains("*"));
    }

    @Test
    void redactKeyValuePair() {
        String result = redactor.redact("DB_PASSWORD=supersecret", true);
        assertTrue(result.contains("[redacted]"));
    }

    @Test
    void redactBearerToken() {
        String result = redactor.redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.token.signature", true);
        assertTrue(result.contains("[redacted]"));
    }

    @Test
    void redactJWT() {
        String jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNqP";
        String result = redactor.redact("token=" + jwt, true);
        assertFalse(result.contains("eyJhbGci"));
    }

    @Test
    void redactDisabled() {
        assertEquals("my key is sk-xxx", redactor.redact("my key is sk-xxx", false));
    }
}
