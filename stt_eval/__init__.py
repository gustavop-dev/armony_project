"""Offline evaluation harness for the live transcription path.

Replays dataset audio through ``stt_stream.StreamingSTT`` at real-time pace,
exactly as ``audio.AudioEngine`` feeds it, and scores the final turns against
reference transcripts (WER/CER) plus turn-finalization latency.

Run ``python -m stt_eval --help``.
"""
