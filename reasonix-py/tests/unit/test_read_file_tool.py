import asyncio
import json

from reasonix.tool.builtin.readfile import ReadFileTool


def test_read_file_outputs_line_numbers_and_file_content(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\n", encoding="utf-8")

    output = asyncio.run(ReadFileTool().execute(json.dumps({"path": str(sample)})))

    assert "      0 | alpha" in output
    assert "      1 | beta" in output
    assert "line.rstrip()" not in output
    assert "\ufffd" not in output
