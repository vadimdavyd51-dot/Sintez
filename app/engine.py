"""Движок озвучки: модель ESpeech + ударения RUAccent + образцы голоса + проверка на слух.
Тяжёлые библиотеки подключаются только в load(), поэтому файл легко проверять отдельно."""
import glob
import hashlib
import json
import os
import re
import sys
import time

import numpy as np
from scipy.io import wavfile

from horror_fx import (PRESETS, build_refs, make_checker, make_horror, normalize_caps, pause_after,
                       pick_voice, save_wav, split_text, synth_checked, to_numpy, trim_silence)
from long_mode import parse_script

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(APP_DIR, "Озвучка")

DEFAULTS = dict(
    project="rasskaz", preset="подкаст", speed=0.9, nfe=48, max_chars=350, line_breaks=True,
    check=True, check_tries=3, check_min=0.85, skip_first=0, read_headings=False,
    part_gap=1.5, pause_scale=1.0, seed=7, use_extra_voices=True,
)


class Stopped(Exception):
    pass


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", (name or "").strip()) or "rasskaz"
    return name[:60]


class Engine:
    def __init__(self, log=print):
        self.log = log
        self.loaded = False

    # ---------- загрузка моделей ----------
    def load(self):
        if self.loaded:
            return
        import torch
        if torch.cuda.is_available():
            self.log(f"Видеокарта: {torch.cuda.get_device_name(0)}")
        else:
            self.log("ВНИМАНИЕ: видеокарта NVIDIA не найдена, озвучка будет очень медленной. См. подсказки в README.")
        self.torch = torch

        from huggingface_hub import hf_hub_download
        from f5_tts.infer.utils_infer import infer_process, load_model, load_vocoder, preprocess_ref_audio_text
        from f5_tts.model import DiT
        self.infer_process, self.prep = infer_process, preprocess_ref_audio_text

        repo = "ESpeech/ESpeech-TTS-1_SFT-256K"
        cfg = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
        self.log("Загружаю модель озвучки (при первом запуске скачивается, это долго)...")
        model_path = hf_hub_download(repo_id=repo, filename="espeech_tts_256k.pt")
        vocab_path = hf_hub_download(repo_id=repo, filename="vocab.txt")
        self.model = load_model(DiT, cfg, model_path, vocab_file=vocab_path)
        self.vocoder = load_vocoder()

        # Совместимость RUAccent с новыми transformers: модели ударений нужен token_type_ids.
        try:
            import onnxruntime as ort
            _orig_run = ort.InferenceSession.run

            def _run(sess, output_names, input_feed, run_options=None):
                names = {i.name for i in sess.get_inputs()}
                if "token_type_ids" in names and "token_type_ids" not in input_feed and "input_ids" in input_feed:
                    input_feed = dict(input_feed)
                    input_feed["token_type_ids"] = np.zeros_like(input_feed["input_ids"])
                return _orig_run(sess, output_names, input_feed, run_options)

            ort.InferenceSession.run = _run
        except Exception as e:
            self.log(f"Патч для RUAccent не применён: {e}")

        from ruaccent import RUAccent
        self.log("Загружаю модель ударений...")
        self.accentizer = RUAccent()
        ruaccent_dir = os.path.join(os.environ.get("HF_HOME", os.path.join(APP_DIR, "models")), "ruaccent")
        os.makedirs(ruaccent_dir, exist_ok=True)
        try:  # модели ударений кладём рядом с остальными, чтобы программа была переносимой
            self.accentizer.load(omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False,
                                 workdir=ruaccent_dir)
        except TypeError:
            self.accentizer.load(omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False)

        self.transcribe = self._make_transcribe()
        self.loaded = True
        self.log("Модели загружены.")

    def _make_transcribe(self):
        """Распознавание речи для проверки на слух. Читает wav сам и отдаёт модели готовый звук:
        так не нужна программа ffmpeg, которой на обычном Windows нет."""
        try:
            from f5_tts.infer import utils_infer as U
            from scipy.signal import resample_poly
        except Exception as e:
            self.log(f"Распознавание речи недоступно: {e}")
            return None

        def tr(path, language="russian"):
            if getattr(U, "asr_pipe", None) is None:
                U.initialize_asr_pipeline()
            sr, data = wavfile.read(path)
            data = data.astype(np.float32)
            if data.ndim > 1:
                data = data.mean(axis=1)
            if data.dtype != np.float32 or np.abs(data).max() > 1.5:
                data = data / 32768.0
            if sr != 16000:
                from math import gcd
                g = gcd(int(sr), 16000)
                data = resample_poly(data, 16000 // g, int(sr) // g).astype(np.float32)
            out = U.asr_pipe({"raw": data, "sampling_rate": 16000}, chunk_length_s=15, batch_size=1,
                             generate_kwargs={"task": "transcribe", "language": language},
                             return_timestamps=False)
            return out["text"]
        return tr

    def preload_asr(self):
        """Скачивает модель распознавания заранее (для проверки на слух)."""
        voices = self.read_voices()
        first = next(iter(voices.values()))
        if self.transcribe:
            self.transcribe(os.path.join(APP_DIR, first["file"]), language="russian")

    # ---------- голоса ----------
    def read_voices(self):
        with open(os.path.join(APP_DIR, "voices.json"), encoding="utf-8") as f:
            return json.load(f)

    def safe_accent(self, t):
        t = normalize_caps(t)
        if "+" in t:  # ударения расставлены вручную
            return t
        try:
            return self.accentizer.process_all(t)
        except Exception as e:
            self.log(f"Ударения для куска не поставились, идёт без них: {repr(e)[:160]}")
            return t

    def build_voices(self, use_extra):
        voices = self.read_voices()
        main = voices["основной"]
        extra = {k: (os.path.join(APP_DIR, v["file"]), v.get("text", ""))
                 for k, v in voices.items() if k != "основной"} if use_extra else {}
        return build_refs(os.path.join(APP_DIR, main["file"]), main["text"], extra,
                          self.safe_accent, self.prep)

    # ---------- озвучка ----------
    @staticmethod
    def signature(text, s, voices_mtime):
        keys = ("preset", "speed", "nfe", "max_chars", "line_breaks", "skip_first", "read_headings",
                "pause_scale", "seed", "use_extra_voices")
        raw = text + json.dumps({k: s[k] for k in keys}, sort_keys=True, ensure_ascii=False) + str(voices_mtime)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def run(self, text, settings, progress, stop):
        """progress(event: dict). stop: объект с is_set(). Возвращает путь к итоговому файлу или None."""
        s = {**DEFAULTS, **settings}
        self.load()
        torch = self.torch
        p = dict(PRESETS[s["preset"]])
        p["pause"] = p["pause"] * float(s["pause_scale"])

        parts, skipped = parse_script(text, int(s["skip_first"]), read_headings=bool(s["read_headings"]))
        if not parts:
            raise ValueError("В тексте нечего озвучивать")
        if skipped:
            self.log("Не озвучиваются первые строки: " + " | ".join(l for _, l in skipped if l))

        out_dir = os.path.join(OUT_ROOT, safe_name(s["project"]))
        os.makedirs(out_dir, exist_ok=True)
        sig_path = os.path.join(out_dir, "_signature.txt")
        sig = self.signature(text, s, os.path.getmtime(os.path.join(APP_DIR, "voices.json")))
        old = open(sig_path, encoding="utf-8").read() if os.path.exists(sig_path) else None
        if old != sig:
            stale = glob.glob(os.path.join(out_dir, "chast_*.wav"))
            if stale and old is not None:
                self.log("Текст или настройки изменились: готовые части удаляю, озвучиваю заново.")
            for f in stale:
                os.remove(f)
            with open(sig_path, "w", encoding="utf-8") as f:
                f.write(sig)

        def part_path(i):
            return os.path.join(out_dir, f"chast_{i:02d}.wav")

        refs = self.build_voices(bool(s["use_extra_voices"]))
        self.log("Образцы голоса в работе: " + ", ".join(refs))
        checker = make_checker(self.transcribe) if (s["check"] and self.transcribe) else None
        self.log("Проверка озвучки на слух: " + ("включена" if checker else "выключена"))
        bad = []

        progress({"type": "parts", "parts": [{"n": i + 1, "title": t, "chars": len(x),
                                               "state": "done" if os.path.exists(part_path(i + 1)) else "wait"}
                                              for i, (t, x) in enumerate(parts)]})

        failed, t0, worked = [], time.time(), 0
        for i, (title, ptext) in enumerate(parts, 1):
            if os.path.exists(part_path(i)):
                self.log(f"Часть {i}/{len(parts)} уже готова, пропускаю: {title}")
                continue
            if stop.is_set():
                raise Stopped()
            ts = time.time()
            self.log(f"Часть {i}/{len(parts)}: {title} ({len(ptext)} знаков)")
            progress({"type": "part", "n": i, "state": "work"})
            try:
                chunks_in = split_text(ptext, int(s["max_chars"]), keep_lines=bool(s["line_breaks"]))
                torch.manual_seed(int(s["seed"]) + i)
                out, sr_ = [], None
                for k, (chunk, par_end) in enumerate(chunks_in, 1):
                    if stop.is_set():
                        raise Stopped()
                    ref_audio, ref_text = refs[pick_voice(chunk, refs)]
                    said = self.safe_accent(chunk)

                    def gen(attempt, said=said, ref_audio=ref_audio, ref_text=ref_text):
                        if attempt:
                            torch.manual_seed(int(s["seed"]) * 1000 + attempt * 77 + len(out))
                        w, sr, _ = self.infer_process(
                            ref_audio, ref_text, said, self.model, self.vocoder,
                            cross_fade_duration=0.15, nfe_step=int(s["nfe"]), speed=float(s["speed"]))
                        return trim_silence(to_numpy(w), sr), sr

                    audio, sr_, _score = synth_checked(gen, chunk, checker, int(s["check_tries"]),
                                                       float(s["check_min"]), bad)
                    out.append((audio, pause_after(chunk, par_end, p["pause"])))
                    progress({"type": "chunk", "n": i, "k": k, "of": len(chunks_in)})
                save_wav(part_path(i), sr_, make_horror(out, sr_, p))
            except Stopped:
                raise
            except Exception as e:
                failed.append(i)
                self.log(f"  ОШИБКА в части {i}, иду дальше: {repr(e)[:300]}")
                progress({"type": "part", "n": i, "state": "fail"})
                continue
            worked += len(ptext)
            left = sum(len(parts[j - 1][1]) for j in range(i + 1, len(parts) + 1) if not os.path.exists(part_path(j)))
            eta = (time.time() - t0) / max(worked, 1) * left / 60
            self.log(f"  готово за {(time.time() - ts) / 60:.1f} мин; до конца примерно {eta:.0f} мин")
            progress({"type": "part", "n": i, "state": "done"})

        if bad:
            self.log(f"У {len(bad)} кусков после {s['check_tries']} попыток есть расхождение с текстом (оценка, текст):")
            for sc, t in bad[:40]:
                self.log(f"  [{sc}] {t}")
        if failed:
            self.log(f"Не получились части: {failed}. Нажми «Озвучить» ещё раз: готовые части пропустятся.")
        return self.merge(out_dir, s["project"], len(parts), float(s["part_gap"]))

    def merge(self, out_dir, project, n_parts, gap):
        paths = sorted(glob.glob(os.path.join(out_dir, "chast_*.wav")))
        if not paths:
            return None
        if len(paths) < n_parts:
            self.log(f"ВНИМАНИЕ: готово частей {len(paths)} из {n_parts}, в итоговый файл войдут только готовые.")
        pieces, sr = [], 24000
        for pth in paths:
            sr, d = wavfile.read(pth)
            pieces.append(d.astype(np.float32) / 32768)
            pieces.append(np.zeros(int(sr * gap), dtype=np.float32))
        full = np.concatenate(pieces[:-1])
        final = os.path.join(out_dir, f"{safe_name(project)}_polnyi.wav")
        save_wav(final, sr, full)
        self.log(f"Итоговый файл: {len(full) / sr / 60:.1f} мин, {os.path.getsize(final) / 1e6:.0f} МБ")
        return final


if __name__ == "__main__":
    if "--preload" in sys.argv:
        e = Engine()
        e.load()
        e.build_voices(True)
        e.preload_asr()
        print("Всё скачано и готово.")
