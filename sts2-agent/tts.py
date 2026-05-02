"""Optional text-to-speech for agent narration via Kokoro (ONNX).

Synthesis + playback run on a background worker thread so speech never blocks
the agent loop. Each speak() call enqueues one turn's text as a single utterance —
batching is per-turn, not per-token.

Requires `kokoro-onnx` and `sounddevice`, plus the Kokoro model files. Defaults
match the Kokoro v1.0 release (`kokoro-v1.0.onnx` + `voices-v1.0.bin`); override
with KOKORO_MODEL / KOKORO_VOICES env vars. Download from:
  https://github.com/thewh1teagle/kokoro-onnx/releases
"""

import os
import queue
import re
import threading


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# Markdown characters that the model sprinkles into prose but that TTS would
# either spell out or stumble on. Stripped before synthesis.
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_CHARS_RE = re.compile(r"[*_`~]")


class TTS:
    def __init__(self, voice: str = "af_sarah", speed: float = 1.1, lang: str = "en-us",
                 debug: bool = True):
        # Lazy imports so the agent runs without these installed when --tts is off.
        from kokoro_onnx import Kokoro
        import sounddevice as sd

        def _find(env_var: str, candidates: list[str]) -> str:
            override = os.environ.get(env_var)
            if override:
                return override
            here = os.path.dirname(os.path.abspath(__file__))
            search_dirs = [os.getcwd(), here, os.path.dirname(here)]
            for d in search_dirs:
                for name in candidates:
                    p = os.path.join(d, name)
                    if os.path.exists(p):
                        return p
            return candidates[0]

        model_path = _find("KOKORO_MODEL", ["kokoro-v1.0.onnx", "kokoro-v0_19.onnx"])
        voices_path = _find("KOKORO_VOICES", ["voices-v1.0.bin", "voices.json"])

        if not os.path.exists(model_path) or not os.path.exists(voices_path):
            raise FileNotFoundError(
                f"Kokoro model files not found ({model_path}, {voices_path}). "
                f"Download from https://github.com/thewh1teagle/kokoro-onnx/releases "
                f"or set KOKORO_MODEL / KOKORO_VOICES."
            )

        # Sanity-check the pair: v0.19 model ↔ voices.json, v1.0 model ↔ voices-v1.0.bin.
        m, v = os.path.basename(model_path), os.path.basename(voices_path)
        mismatched = ("v0_19" in m and v.endswith(".bin")) or ("v1.0" in m and v.endswith(".json"))
        if mismatched:
            raise RuntimeError(
                f"Kokoro model/voices version mismatch: {m} + {v}. "
                f"v0.19 needs voices.json; v1.0 needs voices-v1.0.bin."
            )

        self._kokoro = Kokoro(model_path, voices_path)
        self._sd = sd
        self.voice = voice
        self.speed = speed
        self.lang = lang
        self.debug = debug

        if self.debug:
            try:
                default_out = sd.query_devices(kind="output")
                print(f"[tts] ready — model={model_path} voice={voice} "
                      f"output={default_out['name']!r}", flush=True)
            except Exception as e:
                print(f"[tts] ready — model={model_path} voice={voice} "
                      f"(could not query audio device: {e})", flush=True)

        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def speak(self, text):
        if not text:
            return
        cleaned = _ANSI_RE.sub("", text)
        cleaned = _MD_HEADING_RE.sub("", cleaned)
        cleaned = _MD_CHARS_RE.sub("", cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            return
        if self.debug:
            preview = cleaned if len(cleaned) <= 60 else cleaned[:57] + "..."
            print(f"[tts] queued ({len(cleaned)} chars): {preview}", flush=True)
        self._queue.put(cleaned)

    def wait(self):
        """Block until all queued utterances have finished playing."""
        self._queue.join()

    def stop(self):
        self._queue.put(None)
        try:
            self._sd.stop()
        except Exception:
            pass
        self._thread.join(timeout=2.0)

    def _run(self):
        while True:
            text = self._queue.get()
            if text is None:
                self._queue.task_done()
                return
            try:
                samples, sr = self._kokoro.create(
                    text, voice=self.voice, speed=self.speed, lang=self.lang
                )
                if self.debug:
                    dur = len(samples) / sr if sr else 0
                    print(f"[tts] playing {dur:.1f}s @ {sr}Hz", flush=True)
                self._sd.play(samples, sr)
                self._sd.wait()
            except Exception as e:
                import traceback
                print(f"[tts] synthesis/playback failed: {e}", flush=True)
                if self.debug:
                    traceback.print_exc()
            finally:
                self._queue.task_done()
