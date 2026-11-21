import re
from fractions import Fraction

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, resample_poly, sosfilt

# Пресеты хоррор-режима.
# exaggeration / cfg_weight: настройки самой модели (выразительность и темп).
# rate: <1 замедляет и делает голос ниже. echo, reverb: сила эха и гулкости.
# lowpass: срез верхних частот в Гц (мягче, глуше). pause: множитель пауз.
# room_db: уровень тихого фона комнаты (дБ).
PRESETS = {
    "подкаст": dict(exaggeration=0.5, cfg_weight=0.5, rate=1.0, echo=0.0,
                    reverb=0.0, lowpass=99999, pause=1.0, room_db=-120, highpass=70),
    "рассказчик": dict(exaggeration=0.7, cfg_weight=0.3, rate=0.95, echo=0.0,
                       reverb=0.07, lowpass=12000, pause=1.2, room_db=-120, highpass=70),
    "лёгкий": dict(exaggeration=0.5, cfg_weight=0.5, rate=0.97, echo=0.10,
                   reverb=0.12, lowpass=9000, pause=1.0, room_db=-52),
    "жуткий": dict(exaggeration=0.7, cfg_weight=0.3, rate=0.92, echo=0.18,
                   reverb=0.22, lowpass=7000, pause=1.2, room_db=-46),
    "подвал": dict(exaggeration=0.8, cfg_weight=0.3, rate=0.86, echo=0.28,
                   reverb=0.35, lowpass=5500, pause=1.4, room_db=-42),
}

# Без эффектов: для сохранения "чистой" версии озвучки.
PLAIN = dict(rate=1.0, echo=0.0, reverb=0.0, lowpass=99999, room_db=-120)


def _split_long(para, max_chars):
    """Режет один абзац на куски по предложениям. Возвращает список строк."""
    sentences = [s for s in re.split(r"(?<=[.!?…])\s+", para) if s]
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > max_chars:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    final = []
    for c in chunks:
        while len(c) > int(max_chars * 1.5):
            cut = c.rfind(",", 0, max_chars)
            if cut <= 0:
                cut = c.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars - 1
            final.append(c[:cut + 1].strip())
            c = c[cut + 1:].strip()
        if c:
            final.append(c)
    return final


def split_text(text, max_chars=220, keep_lines=True, min_chars=45):
    """Режет текст на куски. Возвращает [(кусок, конец_абзаца)].
    keep_lines=True: каждый перенос строки - граница фразы (будет пауза), как в ElevenLabs;
    слишком короткие строки (< min_chars) склеиваются со следующей, чтобы модель не сбивалась.
    Пустая строка - конец абзаца (пауза длиннее)."""
    result = []
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    for para in paragraphs:
        if keep_lines:
            lines = [re.sub(r"\s+", " ", l).strip() for l in para.split("\n") if l.strip()]
            units, buf = [], ""
            for l in lines:
                buf = f"{buf} {l}".strip()
                if len(buf) >= min_chars:
                    units.append(buf)
                    buf = ""
            if buf:
                if units and len(buf) < min_chars:
                    units[-1] = f"{units[-1]} {buf}"
                else:
                    units.append(buf)
            final = []
            for u in units:
                final.extend(_split_long(u, max_chars) if len(u) > max_chars else [u])
        else:
            final = _split_long(re.sub(r"\s+", " ", para).strip(), max_chars)
        for i, c in enumerate(final):
            result.append((c, i == len(final) - 1))
    return result


# Аббревиатуры, которые в КАПСЕ оставляем как есть.
CAPS_KEEP = {"СМИ", "США", "СССР", "РФ", "ООН", "НЛО", "ДНК", "ГАИ", "МЧС", "ФСБ", "МВД", "ТВ", "ВДНХ", "ЖЭК", "ЖКХ", "ЗАГС"}


def normalize_caps(text, keep=CAPS_KEEP):
    """ГОЛОС ИЗ ДЕТСКОЙ -> Голос из детской. Слова в КАПСЕ ударения не получают,
    поэтому переводим их в обычный регистр. Аббревиатуры из keep не трогаем.
    Однобуквенные слова (А, В, И, О, У) не трогаем."""
    def fix_line(line):
        def repl(m):
            w = m.group(0)
            if len(w) < 2 or not w.isupper() or w in keep:
                return w
            before = line[:m.start()].rstrip(" «\"“„'(—-–")
            start = not before or before[-1] in ".!?…"
            w = w.lower()
            return w[0].upper() + w[1:] if start else w
        return re.sub(r"[^\W\d_]+", repl, line)
    return "\n".join(fix_line(l) for l in text.split("\n"))


def apply_fixes(text, fixes):
    """Заменяет слова по словарю {слово: как_написать_для_озвучки}, регистр не важен."""
    for word, repl in (fixes or {}).items():
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", repl, text, flags=re.IGNORECASE)
    return text


def pause_after(chunk, paragraph_end, scale=1.0):
    """Длина паузы (сек) после куска: зависит от знака в конце и от конца абзаца.
    Тишина в конце самого куска обрезается trim_silence, так что это вся пауза."""
    last = chunk.rstrip(" »\"”')")[-1:]
    base = {"…": 0.65, ".": 0.38, "?": 0.45, "!": 0.40, ":": 0.45, "—": 0.40, ",": 0.22}.get(last, 0.25)
    if paragraph_end:
        base += 0.45
    return base * scale


def trim_silence(audio, sr, thresh_db=-42, keep=0.05):
    """Срезает тишину в начале и конце куска (модель любит дописывать паузу сама)."""
    a = np.abs(audio)
    if a.size == 0 or a.max() <= 0:
        return audio
    idx = np.where(a > a.max() * 10 ** (thresh_db / 20))[0]
    if idx.size == 0:
        return audio
    k = int(sr * keep)
    return audio[max(idx[0] - k, 0): idx[-1] + k + 1]


def to_numpy(wav):
    """Принимает тензор torch или массив numpy, отдаёт плоский массив float64."""
    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().numpy()
    return np.asarray(wav, dtype=np.float64).squeeze()


def slow_deep(audio, rate):
    """Замедляет и понижает голос (как плёнку на меньшей скорости)."""
    if abs(rate - 1.0) < 1e-3:
        return audio
    f = Fraction(1.0 / rate).limit_denominator(100)
    return resample_poly(audio, f.numerator, f.denominator)


def lowpass(audio, sr, cutoff):
    if cutoff >= sr / 2:
        return audio
    sos = butter(4, cutoff, btype="low", fs=sr, output="sos")
    return sosfilt(sos, audio)


def highpass(audio, sr, cutoff):
    """Срезает гул и рокот ниже cutoff Гц."""
    if not cutoff:
        return audio
    sos = butter(2, cutoff, btype="high", fs=sr, output="sos")
    return sosfilt(sos, audio)


def add_echo(audio, sr, amount, delay=0.32, taps=4):
    if amount <= 0:
        return audio
    out = audio.copy()
    for k in range(1, taps + 1):
        d = int(sr * delay * k)
        if d >= len(audio):
            break
        out[d:] += audio[:-d] * (amount * 0.6 ** (k - 1))
    return out


def add_reverb(audio, sr, amount, rt60=2.2, seed=0):
    """Гулкое помещение: свёртка с затухающим шумом, тёмный тембр хвоста."""
    if amount <= 0:
        return audio
    rng = np.random.default_rng(seed)
    n = int(sr * rt60)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n) * np.exp(-6.9 * t / rt60)
    ir = lowpass(ir, sr, 3500)
    ir[:int(0.02 * sr)] = 0.0
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    wet = fftconvolve(audio, ir)[:len(audio)]
    dry_rms = np.sqrt(np.mean(audio ** 2)) + 1e-9
    wet_rms = np.sqrt(np.mean(wet ** 2)) + 1e-9
    return audio + amount * wet * (dry_rms / wet_rms)


def room_tone(n, sr, db, seed=1):
    rng = np.random.default_rng(seed)
    noise = lowpass(rng.standard_normal(n), sr, 500)
    noise /= np.max(np.abs(noise)) + 1e-9
    return noise * 10 ** (db / 20)


def make_horror(parts, sr, p):
    """parts: [(аудио, пауза_после_сек)]. Возвращает готовую дорожку float32."""
    pieces = []
    for i, (audio, pause) in enumerate(parts):
        pieces.append(slow_deep(audio, p["rate"]))
        if i < len(parts) - 1:
            pieces.append(np.zeros(int(sr * pause)))
    pieces.append(np.zeros(int(sr * 2.0)))  # хвост для эха и гула
    track = np.concatenate(pieces).astype(np.float64)
    track = add_echo(track, sr, p["echo"])
    track = add_reverb(track, sr, p["reverb"])
    track = lowpass(track, sr, p["lowpass"])
    track = highpass(track, sr, p.get("highpass", 0))
    track = track / (np.max(np.abs(track)) + 1e-9) * 0.89
    track = track + room_tone(len(track), sr, p["room_db"])
    return np.clip(track, -1.0, 1.0).astype(np.float32)


def save_wav(path, sr, audio):
    wavfile.write(path, sr, (np.clip(audio, -1, 1) * 32767).astype(np.int16))


def build_refs(main_path, main_text, extra, accent, prep):
    """Готовит образцы: {"основной": (аудио, текст), "напряжённый": ..., "тихий": ...}.
    extra: {"напряжённый": ("файл.wav", "что сказано"), ...}; accent - функция ударений;
    prep - preprocess_ref_audio_text. Пустой текст = модель сама распознаёт, что сказано в записи."""
    def make(path, text):
        text = (text or "").strip()
        if not text:
            audio, said = prep(path, "")
            print(f"  распознано в {path.split('/')[-1]}: {said.strip()}")
            return audio, (said if "+" in said else accent(normalize_caps(said)))
        return prep(path, text if "+" in text else accent(normalize_caps(text)))
    refs = {"основной": make(main_path, main_text)}
    for name, (path, text) in (extra or {}).items():
        if path and "ВПИШИ" not in (text or ""):
            refs[name] = make(path, text)
    return refs


def pick_voice(chunk, refs):
    """Выбор образца по смыслу куска: восклицания и реплики - напряжённый, многоточие - тихий."""
    t = chunk.strip()
    if "напряжённый" in refs and ("!" in t or t[:1] in "«—\"" ):
        return "напряжённый"
    if "тихий" in refs and t.rstrip(" »\"”')").endswith("…"):
        return "тихий"
    return "основной"


def _norm_words(t):
    t = t.lower().replace("ё", "е").replace("+", "")
    return re.findall(r"[a-zа-я0-9]+", t)


def similarity(said, wanted):
    """Насколько распознанная речь совпала с текстом (0..1), по буквам и без учёта регистра и знаков."""
    import difflib
    a, b = " ".join(_norm_words(said)), " ".join(_norm_words(wanted))
    if not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def make_checker(transcribe, sr_save=save_wav):
    """Проверка озвучки на слух: распознаёт куски и сравнивает с текстом.
    Если распознавалка не работает, сама отключается (возвращает None-оценку)."""
    state = {"ok": True}

    def check(audio, sr, text):
        if not state["ok"]:
            return None
        import os, tempfile
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            sr_save(path, sr, audio)
            said = transcribe(path, language="russian") if _accepts_language(transcribe) else transcribe(path)
            return similarity(said, text)
        except Exception as e:
            print("Проверка озвучки отключена (распознавание не заработало):", repr(e)[:160])
            state["ok"] = False
            return None
        finally:
            if path and os.path.exists(path):
                os.remove(path)
    return check


def _accepts_language(fn):
    import inspect
    try:
        return "language" in inspect.signature(fn).parameters
    except Exception:
        return False


def synth_checked(gen, text, checker, tries=3, min_score=0.85, bad=None):
    """gen(попытка) -> (аудио, sr). Озвучивает кусок, проверяет, при ошибке пробует снова.
    Берёт лучшую попытку. Куски, которые так и не совпали, записывает в bad."""
    best = None
    for attempt in range(max(1, tries if checker else 1)):
        audio, sr = gen(attempt)
        score = checker(audio, sr, text) if checker else None
        if score is None:
            return audio, sr, None
        if best is None or score > best[2]:
            best = (audio, sr, score)
        if score >= min_score:
            break
    if best[2] < min_score and bad is not None:
        bad.append((round(best[2], 2), text))
    return best
