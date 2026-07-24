package com.reasonix.security.guardian;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;

/**
 * 转录光标 — 跟踪已发送给 guardian 的转录条目。
 * 每次只发增量，保持 LLM 前缀缓存稳定。
 *
 * 映射 Go 的 internal/guardian/transcript.go TranscriptCursor。
 */
public class TranscriptCursor {

    private static final Logger log = LoggerFactory.getLogger(TranscriptCursor.class);
    private static final ObjectMapper mapper = new ObjectMapper();

    private int entryCount = 0;

    /**
     * 计算增量转录。
     * @param transcriptJson 当前完整的转录（JSON 数组字符串）
     * @return 增量转录文本（或 "no new entries"）
     */
    public String delta(String transcriptJson) {
        try {
            var entries = mapper.readValue(transcriptJson, List.class);
            int total = entries.size();

            if (total <= entryCount) {
                return ">>> TRANSCRIPT: no new entries since last review\n";
            }

            // 只取新的条目
            var newEntries = entries.subList(entryCount, total);
            var sb = new StringBuilder();
            sb.append(">>> TRANSCRIPT DELTA (").append(newEntries.size()).append(" new) <<<\n");
            for (int i = 0; i < newEntries.size(); i++) {
                var entry = newEntries.get(i);
                var text = entry instanceof String s ? s : entry.toString();
                if (text.length() > 2000) text = text.substring(0, 2000) + "...";
                sb.append("[").append(entryCount + i + 1).append("] ").append(text).append("\n");
            }
            sb.append(">>> TRANSCRIPT DELTA END <<<");

            entryCount = total;
            return sb.toString();

        } catch (JsonProcessingException e) {
            log.warn("Failed to parse transcript JSON, sending full: {}", e.getMessage());
            return transcriptJson;
        }
    }

    public int getEntryCount() {
        return entryCount;
    }
}
