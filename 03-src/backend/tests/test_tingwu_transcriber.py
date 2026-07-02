"""Unit tests for Tingwu ASR format conversion."""

import json
from pathlib import Path

from app.s2_parse.audio.tingwu_transcriber import (
    save_tingwu_raw_json,
    tingwu_json_path_from_transcript_base,
    tingwu_to_verbose,
)


def test_tingwu_json_path_from_transcript_base():
    base = Path(
        "data/02_parse/xiaoyuzhou/20260702/002-title/c1e8b961-8ab7-4547-9347-5eacf46ad9f4_asr.json"
    )
    out = tingwu_json_path_from_transcript_base(base)
    assert out.name == "c1e8b961-8ab7-4547-9347-5eacf46ad9f4_tingwu.json"
    assert out.parent == base.parent


def test_save_tingwu_raw_json(tmp_path: Path):
    base = tmp_path / "job-id_asr.json"
    payload = {"TaskId": "demo", "Transcription": {"Paragraphs": []}}
    out = save_tingwu_raw_json(payload, base)
    assert out.name == "job-id_tingwu.json"
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["TaskId"] == "demo"


def test_tingwu_to_verbose_groups_sentences_and_timestamps():
  payload = {
    "TaskId": "demo",
    "Transcription": {
      "AudioInfo": {"Duration": 10000, "Language": "cn"},
      "Paragraphs": [
        {
          "ParagraphId": "p1",
          "SpeakerId": "1",
          "Words": [
            {"Id": 1, "SentenceId": 1, "Start": 1000, "End": 1500, "Text": "你好"},
            {"Id": 2, "SentenceId": 1, "Start": 1500, "End": 2000, "Text": "世界"},
            {"Id": 3, "SentenceId": 2, "Start": 3000, "End": 4500, "Text": "第二句"},
          ],
        }
      ],
    },
  }

  verbose = tingwu_to_verbose(payload)

  assert verbose["text"] == "你好世界第二句"
  assert verbose["language"] == "zh"
  assert verbose["duration"] == 10.0
  assert len(verbose["segments"]) == 2
  assert verbose["segments"][0]["start"] == 1.0
  assert verbose["segments"][0]["end"] == 2.0
  assert verbose["segments"][0]["text"] == "你好世界"
  assert verbose["segments"][1]["text"] == "第二句"
