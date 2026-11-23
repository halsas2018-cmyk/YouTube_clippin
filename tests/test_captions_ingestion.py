"""Comprehensive unit tests for captions extraction, whitespace normalization,
filename parsing, language normalization, duplicate handling, fallback errors,
and downstream compatibility.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.transcript_discovery.clipper import _format_transcript_for_llm, _load_transcript
from src.youtube_ingestion import cli
from src.youtube_ingestion.captions import (
    _extract_lang_from_filename,
    fetch_all_transcripts,
    fetch_transcripts_via_ytdlp,
    parse_json3_subtitles,
    parse_vtt_subtitles,
)
from src.youtube_ingestion.ingester import Ingester


class TestCaptionsIngestion(unittest.TestCase):
    """Test suite for captions parsing, fallback, and ingestion."""

    def test_vtt_parser_whitespace_normalization(self):
        """Verify VTT parser normalizes whitespace using ' '.join(clean_text.split()).strip()

        and does NOT join words with newlines.
        """
        vtt_content = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:04.000 align:start position:0%
Line one with words
and line two with words
\tand  line   three\twith   extra   spaces

00:00:05.000 --> 00:00:08.000
<c.colorE5E5E5>Styled</c>
tag
with
multiple
newlines
"""
        segments = parse_vtt_subtitles(vtt_content)
        self.assertEqual(len(segments), 2)

        # Segment 1: must be single-spaced with no newlines or tabs
        self.assertEqual(
            segments[0]["text"],
            "Line one with words and line two with words and line three with extra spaces",
        )
        self.assertNotIn("\n", segments[0]["text"])
        self.assertNotIn("\t", segments[0]["text"])
        self.assertNotIn("  ", segments[0]["text"])
        self.assertEqual(segments[0]["start"], 1.0)
        self.assertEqual(segments[0]["duration"], 3.0)

        # Segment 2: tags removed, words joined with spaces (not newlines)
        self.assertEqual(segments[1]["text"], "Styled tag with multiple newlines")
        self.assertNotIn("\n", segments[1]["text"])
        self.assertEqual(segments[1]["start"], 5.0)
        self.assertEqual(segments[1]["duration"], 3.0)

    def test_vtt_parser_srt_support_and_deduplication(self):
        """Verify SRT format support and deduplication of consecutive identical cues."""
        srt_content = """1
00:00:01,200 --> 00:00:03,500
Repeating phrase

2
00:00:01,400 --> 00:00:03,500
Repeating phrase

3
00:00:04,000 --> 00:00:06,000
Next phrase &amp; more
"""
        segments = parse_vtt_subtitles(srt_content)
        # The second repeating cue should be deduplicated
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["text"], "Repeating phrase")
        self.assertEqual(segments[0]["start"], 1.2)
        self.assertEqual(segments[1]["text"], "Next phrase & more")
        self.assertEqual(segments[1]["start"], 4.0)

    def test_json3_parser(self):
        """Verify JSON3 parser correctly parses events, unescapes HTML, and collapses whitespace."""
        json3_data = {
            "events": [
                {
                    "tStartMs": 1200,
                    "dDurationMs": 2800,
                    "segs": [
                        {"utf8": "Hello\n"},
                        {"utf8": "world &quot;friend&quot;"},
                    ],
                },
                {
                    "tStartMs": 4000,
                    "dDurationMs": 1500,
                    "segs": [{"utf8": "Next line"}],
                },
                # Event without tStartMs or empty text should be skipped
                {"dDurationMs": 1000, "segs": [{"utf8": "No timestamp"}]},
                {"tStartMs": 6000, "segs": [{"utf8": "   \n\t  "}]},
            ]
        }
        segments = parse_json3_subtitles(json.dumps(json3_data))
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["text"], 'Hello world "friend"')
        self.assertEqual(segments[0]["start"], 1.2)
        self.assertEqual(segments[0]["duration"], 2.8)
        self.assertEqual(segments[1]["text"], "Next line")
        self.assertEqual(segments[1]["start"], 4.0)
        self.assertEqual(segments[1]["duration"], 1.5)

    def test_regression_vtt_words_on_single_line_space_separated(self):
        """Regression test: assert that words within multi-line VTT cues remain space-separated on one line."""
        vtt_cue = """WEBVTT

00:00:02.000 --> 00:00:05.000
First
Second
Third
Fourth
"""
        segments = parse_vtt_subtitles(vtt_cue)
        self.assertEqual(len(segments), 1)
        seg_text = segments[0]["text"]
        # Must be on a single line, space-separated, no newlines
        self.assertEqual(seg_text, "First Second Third Fourth")
        self.assertNotIn("\n", seg_text)
        self.assertNotIn("\r", seg_text)
        self.assertEqual(len(seg_text.splitlines()), 1)
        self.assertEqual(seg_text.split(" "), ["First", "Second", "Third", "Fourth"])

    def test_regression_json3_words_on_single_line_space_separated(self):
        """Regression test: assert that words across JSON3 segs with newlines remain space-separated on one line."""
        json3_event = {
            "events": [
                {
                    "tStartMs": 3000,
                    "dDurationMs": 4000,
                    "segs": [
                        {"utf8": "Alpha\n"},
                        {"utf8": "Beta\r\n"},
                        {"utf8": "\tGamma "},
                        {"utf8": "Delta"},
                    ],
                }
            ]
        }
        segments = parse_json3_subtitles(json.dumps(json3_event))
        self.assertEqual(len(segments), 1)
        seg_text = segments[0]["text"]
        # Must be on a single line, space-separated, no newlines
        self.assertEqual(seg_text, "Alpha Beta Gamma Delta")
        self.assertNotIn("\n", seg_text)
        self.assertNotIn("\r", seg_text)
        self.assertEqual(len(seg_text.splitlines()), 1)
        self.assertEqual(seg_text.split(" "), ["Alpha", "Beta", "Gamma", "Delta"])

    def test_filename_extraction(self):
        """Verify subtitle filename parsing handles language tags and extensions."""
        video_id = "BgeNDG5jD60"

        self.assertEqual(_extract_lang_from_filename(f"{video_id}.en.json3", video_id), ("en", "json3"))
        self.assertEqual(_extract_lang_from_filename(f"{video_id}.en-orig.vtt", video_id), ("en-orig", "vtt"))
        self.assertEqual(_extract_lang_from_filename(f"{video_id}.en_US.srt", video_id), ("en-US", "srt"))
        self.assertEqual(_extract_lang_from_filename(f"{video_id}.es.vtt", video_id), ("es", "vtt"))
        self.assertEqual(_extract_lang_from_filename(f"{video_id}.vtt", video_id), ("en", "vtt"))

    def test_ytdlp_language_normalization_and_deduplication(self):
        """Verify yt-dlp fallback normalizes English tracks, avoids duplicates,

        and prefers manual 'en' over auto-generated 'en-orig'.
        """
        video_id = "TESTVID1234"
        sample_json3 = json.dumps({
            "events": [
                {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Manual caption"}]}
            ]
        })
        auto_json3 = json.dumps({
            "events": [
                {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Auto caption"}]}
            ]
        })

        # Case A: Both manual 'en' and auto 'en-orig' files exist
        def fake_subprocess_both(cmd, capture_output=True, text=True):
            out_idx = cmd.index("-o") + 1
            out_dir = Path(cmd[out_idx]).parent
            (out_dir / f"{video_id}.en.json3").write_text(sample_json3, encoding="utf-8")
            (out_dir / f"{video_id}.en-orig.json3").write_text(auto_json3, encoding="utf-8")
            # .part file should be ignored
            (out_dir / f"{video_id}.en.vtt.part").write_text("partial", encoding="utf-8")
            res = MagicMock()
            res.returncode = 0
            return res

        with patch("subprocess.run", side_effect=fake_subprocess_both):
            results = fetch_transcripts_via_ytdlp(video_id, languages=["en"])
            # Should contain exact 'en' manual transcript, and NOT duplicate with auto 'en-orig'
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["language_code"], "en")
            self.assertFalse(results[0]["is_generated"])
            self.assertEqual(results[0]["segments"][0]["text"], "Manual caption")

        # Case B: Only auto 'en-orig' exists
        def fake_subprocess_auto_only(cmd, capture_output=True, text=True):
            out_idx = cmd.index("-o") + 1
            out_dir = Path(cmd[out_idx]).parent
            (out_dir / f"{video_id}.en-orig.json3").write_text(auto_json3, encoding="utf-8")
            res = MagicMock()
            res.returncode = 0
            return res

        with patch("subprocess.run", side_effect=fake_subprocess_auto_only):
            results = fetch_transcripts_via_ytdlp(video_id, languages=["en"])
            # Must be normalized to 'en' with is_generated=True
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["language_code"], "en")
            self.assertTrue(results[0]["is_generated"])
            self.assertEqual(results[0]["segments"][0]["text"], "Auto caption")

    def test_ytdlp_fallback_error_handling(self):
        """Verify yt-dlp fallback handles errors gracefully without crashing."""
        with patch("subprocess.run", side_effect=Exception("Subprocess crashed")):
            results = fetch_transcripts_via_ytdlp("ERRORVID123")
            self.assertEqual(results, [])

    def test_fetch_all_transcripts_fallback_routing(self):
        """Verify fetch_all_transcripts falls back to yt-dlp when youtube-transcript-api fails

        or returns empty, while preventing duplicate entries.
        """
        video_id = "FALLBACK123"
        fake_ytdlp_res = [
            {
                "video_id": video_id,
                "language_code": "en",
                "language": "English (auto-generated)",
                "is_generated": True,
                "is_translatable": True,
                "translation_languages": [],
                "segments": [{"text": "Fallback text", "start": 0.0, "duration": 2.0}],
            }
        ]

        # When youtube-transcript-api raises an exception
        with patch("src.youtube_ingestion.captions.YouTubeTranscriptApi.list", side_effect=Exception("Blocked")):
            with patch("src.youtube_ingestion.captions.fetch_transcripts_via_ytdlp", return_value=fake_ytdlp_res):
                transcripts = fetch_all_transcripts(video_id, languages=["en"])
                self.assertEqual(len(transcripts), 1)
                self.assertEqual(transcripts[0]["language_code"], "en")
                self.assertEqual(transcripts[0]["segments"][0]["text"], "Fallback text")

        # When youtube-transcript-api returns transcripts for another language not matching request
        mock_item = MagicMock()
        mock_item.language_code = "es"
        with patch("src.youtube_ingestion.captions.YouTubeTranscriptApi.list", return_value=[mock_item]):
            with patch("src.youtube_ingestion.captions.fetch_transcripts_via_ytdlp", return_value=fake_ytdlp_res):
                transcripts = fetch_all_transcripts(video_id, languages=["en"])
                self.assertEqual(len(transcripts), 1)
                self.assertEqual(transcripts[0]["language_code"], "en")

    def test_downstream_schema_and_path_compatibility(self):
        """End-to-end ingestion test verifying that the output matches the exact

        path and schema expected by downstream stages (e.g. transcript_discovery).
        """
        video_id = "DOWNSTREAM1"
        raw_metadata = {
            "id": video_id,
            "title": "Downstream Test Video",
            "description": "Test description",
            "duration": 120.0,
            "duration_string": "02:00",
            "upload_date": "20260101",
            "uploader": "Test Channel",
        }
        sample_segments = [
            {"text": "First segment line", "start": 0.0, "duration": 3.5},
            {"text": "Second segment line", "start": 3.5, "duration": 4.0},
        ]
        fake_transcripts = [
            {
                "video_id": video_id,
                "language_code": "en",
                "language": "English (auto-generated)",
                "is_generated": True,
                "is_translatable": True,
                "translation_languages": [],
                "segments": sample_segments,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            downloads_dir = Path(tmpdir)
            ingester = Ingester(download_dir=downloads_dir)

            with patch("src.youtube_ingestion.ingester.fetch_metadata", return_value=raw_metadata):
                with patch("src.youtube_ingestion.ingester.fetch_all_transcripts", return_value=fake_transcripts):
                    res = ingester.ingest(f"https://youtu.be/{video_id}", languages=["en"])

            # 1. Verify file paths
            expected_en_path = downloads_dir / video_id / "transcripts" / "en.json"
            self.assertTrue(expected_en_path.exists())
            self.assertEqual(res.transcript_paths, [expected_en_path])
            self.assertEqual(res.languages, ["en"])

            # 2. Verify schema matches downstream requirements
            with expected_en_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)

            required_keys = ["video_id", "language_code", "language", "is_generated", "segments"]
            for k in required_keys:
                self.assertIn(k, data)

            self.assertEqual(data["video_id"], video_id)
            self.assertEqual(data["language_code"], "en")
            self.assertIsInstance(data["segments"], list)
            self.assertEqual(len(data["segments"]), 2)

            for seg in data["segments"]:
                self.assertIn("text", seg)
                self.assertIsInstance(seg["text"], str)
                self.assertIn("start", seg)
                self.assertIsInstance(seg["start"], (int, float))
                self.assertIn("duration", seg)
                self.assertIsInstance(seg["duration"], (int, float))

            # 3. Verify downstream transcript_discovery functions load it cleanly
            with patch("src.transcript_discovery.clipper._DOWNLOADS_ROOT", downloads_dir):
                loaded = _load_transcript(video_id)
                self.assertEqual(loaded["video_id"], video_id)
                formatted = _format_transcript_for_llm(loaded["segments"])
                self.assertIn("First segment line", formatted)
                self.assertIn("Second segment line", formatted)

    def test_pipeline_failure_when_no_transcripts(self):
        """Verify ingestion clearly reports failure when no transcripts are found."""
        video_id = "NOTRANSCRIPT1"
        raw_metadata = {"id": video_id, "title": "No Transcript Video"}

        with tempfile.TemporaryDirectory() as tmpdir:
            ingester = Ingester(download_dir=Path(tmpdir))

            with patch("src.youtube_ingestion.ingester.fetch_metadata", return_value=raw_metadata):
                with patch("src.youtube_ingestion.ingester.fetch_all_transcripts", return_value=[]):
                    # Ingester.ingest must raise RuntimeError
                    with self.assertRaises(RuntimeError) as exc_info:
                        ingester.ingest(f"https://youtu.be/{video_id}", languages=["en"])
                    self.assertIn("Ingestion failed: No transcripts could be extracted", str(exc_info.exception))

                    # CLI main must exit with code 1
                    with patch("sys.argv", ["youtube-ingest", f"https://youtu.be/{video_id}"]):
                        exit_code = cli.main()
                        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
