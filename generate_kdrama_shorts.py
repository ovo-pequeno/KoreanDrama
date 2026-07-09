# =========================================================
# 韓国ドラマ頻出フレーズ聞き流し｜Shorts（フレーズ集）
# ハングル＋カタカナ発音＋和訳の3段表示。gTTS(ko)で読み上げ。
# 【完全創作・汎用フレーズ】実在ドラマ名/俳優名/実セリフは使わず、
#   「ドラマによく出るタイプの日常フレーズ」を汎用表現として作る。
# Gemini → gTTS(ko) → MoviePy → YouTube API / 縦型1080x1920
# =========================================================
import os, re, json, time, gc
from google import genai
try:
    from google.genai import types as genai_types
except Exception:
    genai_types = None
from gtts import gTTS
from pydub import AudioSegment
from moviepy.editor import (
    ColorClip, ImageClip, TextClip, CompositeVideoClip, AudioFileClip, CompositeAudioClip
)
import moviepy.config as cf
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

cf.change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

GEMINI_API_KEY   = os.environ["GEMINI_API_KEY"]
YT_CLIENT_ID     = os.environ["YT_CLIENT_ID"]
YT_CLIENT_SECRET = os.environ["YT_CLIENT_SECRET"]
YT_REFRESH_TOKEN = os.environ["YT_REFRESH_TOKEN"]

PRIVACY = os.environ.get("PRIVACY", "public")
MODEL   = os.environ.get("MODEL", "gemini-2.5-flash")

GTTS_LANG    = "ko"
VOICE_SPEED  = 1.0
NUM_PHRASES  = int(os.environ.get("NUM_PHRASES", "7"))   # Shorts 1本のフレーズ数
OUT_DIR  = "out_s"
TMP_DIR  = "tmp_s"
LOG_PATH = "used_log_kdrama_shorts.json"
AVOID_RECENT = 40

BG_IMAGE = "assets/bg_short.png" if os.path.exists("assets/bg_short.png") else None
BG_COLOR = (30, 18, 34)     # 落ち着いた紫（韓ドラっぽさ）
BGM_PATH = "assets/bgm.mp3" if os.path.exists("assets/bgm.mp3") else None
BGM_VOLUME = 0.08

client = genai.Client(api_key=GEMINI_API_KEY)

W, H = 1080, 1920
FPS = 10

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"   # ハングル・日本語両対応
TEXT_COLOR = "white"
KANA_COLOR = "#FFD27F"      # カタカナ発音は淡いオレンジ
JA_COLOR   = "#7FC0FF"      # 和訳は水色
STROKE_COLOR = "#000000"
HANGUL_FS  = 92
KANA_FS    = 52
JA_FS      = 50
HEADER_FS  = 44
HEADER_TEXT = "ドラマ韓国語"


def load_log():
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_log(log):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)


def generate_phrases(avoid_summaries, max_retries=5):
    models = [MODEL, "gemini-2.5-flash-lite", "gemini-3.1-flash-lite"]
    avoid_text = ""
    if avoid_summaries:
        joined = "\n".join(f"- {s}" for s in avoid_summaries)
        avoid_text = f"\n\n【これらと被らない別テーマ・別フレーズにする】\n{joined}"
    prompt = f"""あなたは韓国語の先生で、韓流ドラマ好きの日本人初心者向けに
「ドラマでよく聞くタイプの韓国語フレーズ集」を作ります。

重要な制約：
- 実在のドラマ名・俳優名・アイドル名・実際のセリフは一切使わない。
- あくまで「ドラマによく出てくるような“汎用的な”日常フレーズ」を自分で考える。
- 初心者向けに、短くて実用的なフレーズにする。
- テーマ（場面）を自分で1つ決める（日常会話／告白／ファンミ／買い物／喧嘩／あいさつ 等、毎回変える）。

各フレーズに「ハングル」「カタカナ発音」「日本語訳」を付ける。
カタカナ発音は、日本人が読めるように自然なカタカナで（例：사랑해요→サランヘヨ）。

以下のJSON形式のみで出力（前後に説明・マークダウン不要）:
{{
  "theme": "今回の場面・テーマ（被り防止ログ用・30文字以内）",
  "youtube_title": "タップしたくなる日本語タイトル（30文字以内・推し活/ドラマ感を出す）",
  "phrases": [
    {{"hangul": "ハングル", "kana": "カタカナ発音", "ja": "日本語訳"}}
  ]
}}
※phrasesは必ず{NUM_PHRASES}個。各フレーズは短く実用的に。{avoid_text}
"""
    cfg = genai_types.GenerateContentConfig(temperature=1.1) if genai_types else None
    for attempt in range(max_retries):
        m = models[min(attempt, len(models) - 1)]
        try:
            if cfg:
                resp = client.models.generate_content(model=m, contents=prompt, config=cfg)
            else:
                resp = client.models.generate_content(model=m, contents=prompt)
            text = resp.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(text)
            if not data.get("phrases"):
                raise ValueError("phrasesが空")
            return data
        except Exception as e:
            msg = str(e)
            if ("503" in msg or "429" in msg or "UNAVAILABLE" in msg) and attempt < max_retries - 1:
                time.sleep(20 * (attempt + 1))
            elif attempt < max_retries - 1:
                time.sleep(5)
            else:
                raise


def make_audio_ko(text, filename, repeat=True):
    """フレーズを読み上げ。repeat=Trueで「ふつう→間→ゆっくり」の2回読み。"""
    if not text.strip():
        AudioSegment.silent(duration=400).export(filename, format="mp3")
        return filename
    n_tmp = "n_" + filename
    gTTS(text=text, lang=GTTS_LANG, slow=False).save(n_tmp)
    normal = AudioSegment.from_mp3(n_tmp)
    if VOICE_SPEED and VOICE_SPEED != 1.0:
        normal = normal.speedup(playback_speed=VOICE_SPEED)
    if repeat:
        s_tmp = "s_" + filename
        gTTS(text=text, lang=GTTS_LANG, slow=True).save(s_tmp)
        slow = AudioSegment.from_mp3(s_tmp)
        combined = normal + AudioSegment.silent(duration=500) + slow + AudioSegment.silent(duration=400)
        os.remove(s_tmp)
    else:
        combined = normal + AudioSegment.silent(duration=400)
    combined.export(filename, format="mp3")
    os.remove(n_tmp)
    return filename


_BG_CACHE = None
def _fit_bg(path):
    global _BG_CACHE
    if _BG_CACHE is None:
        from PIL import Image
        import numpy as np
        resample = getattr(Image, "Resampling", Image).LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        _BG_CACHE = np.array(Image.open(path).convert("RGB").resize((W, H), resample))
    return _BG_CACHE


def make_bg(duration):
    if BG_IMAGE and os.path.exists(BG_IMAGE):
        return ImageClip(_fit_bg(BG_IMAGE)).set_duration(duration)
    return ColorClip(size=(W, H), color=BG_COLOR, duration=duration)


def _prewrap(text, fontsize, canvas_w):
    import textwrap
    is_latin = sum(ord(c) < 128 for c in text) > len(text) * 0.6
    factor = 0.58 if is_latin else 1.05
    max_chars = max(6, int(canvas_w / (fontsize * factor)))
    if is_latin:
        return "\n".join(textwrap.wrap(text, width=max_chars)) or text
    return "\n".join(text[i:i + max_chars] for i in range(0, len(text), max_chars)) or text


def make_outlined(text, duration, fontsize, color, stroke_w=8, ypos="center", size=None):
    if size is None:
        size = (W - 100, None)
    wrapped = _prewrap(text, fontsize, size[0])
    common = dict(font=FONT, fontsize=fontsize, method="label", align="center", interline=12)
    stroke = TextClip(wrapped, color=STROKE_COLOR, stroke_color=STROKE_COLOR,
                      stroke_width=stroke_w, **common).set_duration(duration)
    fill = TextClip(wrapped, color=color, **common).set_duration(duration)
    grp = CompositeVideoClip(
        [stroke.set_position(("center", "center")), fill.set_position(("center", "center"))],
        size=(max(stroke.w, fill.w), max(stroke.h, fill.h))
    ).set_duration(duration)
    return grp.set_position(("center", ypos))


def make_scene(hangul, kana, ja, audio_file):
    narration = AudioFileClip(audio_file)
    duration = narration.duration + 0.5
    layers = [make_bg(duration)]
    layers.append(make_outlined(HEADER_TEXT, duration, HEADER_FS, "#E7A8FF",
                                 stroke_w=5, ypos=int(H * 0.07)))
    layers.append(make_outlined(hangul, duration, HANGUL_FS, TEXT_COLOR,
                                 stroke_w=10, ypos=int(H * 0.34)))
    layers.append(make_outlined(kana, duration, KANA_FS, KANA_COLOR,
                                 stroke_w=8, ypos=int(H * 0.52)))
    layers.append(make_outlined(ja, duration, JA_FS, JA_COLOR,
                                 stroke_w=8, ypos=int(H * 0.64)))
    scene = CompositeVideoClip(layers, size=(W, H)).set_duration(duration)
    if duration > narration.duration + 0.02:
        narration = CompositeAudioClip([narration]).set_duration(duration)
    return scene.set_audio(narration)


def render(scene, out_path):
    scene.write_videofile(out_path, fps=FPS, codec="libx264",
                          audio_codec="aac", preset="ultrafast", logger=None)
    try:
        if scene.audio is not None:
            scene.audio.close()
    except Exception:
        pass
    scene.close(); del scene; gc.collect()


def build_video(data):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)
    title = data.get("youtube_title", "ドラマ韓国語フレーズ")
    safe = title
    for ch in r'\/:*?"<>|':
        safe = safe.replace(ch, "")
    output_path = os.path.join(OUT_DIR, f"{safe.strip()[:60]}.mp4")

    clip_paths = []
    idx = 0
    for i, p in enumerate(data["phrases"]):
        hangul = (p.get("hangul") or "").strip()
        kana = (p.get("kana") or "").strip()
        ja = (p.get("ja") or "").strip()
        if not hangul:
            continue
        print(f"  [{i+1}/{len(data['phrases'])}] {hangul}")
        a = make_audio_ko(hangul, f"a_{idx}.mp3", repeat=True)
        pth = f"{TMP_DIR}/clip_{idx:04d}.mp4"
        render(make_scene(hangul, kana, ja, a), pth)
        clip_paths.append(pth); os.remove(a); idx += 1

    list_file = f"{TMP_DIR}/list.txt"
    with open(list_file, "w") as f:
        for cp in clip_paths:
            f.write(f"file '{os.path.basename(cp)}'\n")
    master = f"{TMP_DIR}/master.mp4"
    os.system(f'cd {TMP_DIR} && ffmpeg -y -f concat -safe 0 -i list.txt -c:v copy -c:a aac master.mp4 -loglevel error')
    if BGM_PATH and os.path.exists(BGM_PATH):
        os.system(
            f'ffmpeg -y -i "{master}" -stream_loop -1 -i "{BGM_PATH}" '
            f'-filter_complex "[1:a]volume={BGM_VOLUME}[b];[0:a][b]amix=inputs=2:duration=first:dropout_transition=0[a]" '
            f'-map 0:v -map "[a]" -c:v copy -c:a aac "{output_path}" -loglevel error')
    else:
        os.replace(master, output_path)
    for cp in clip_paths:
        if os.path.exists(cp): os.remove(cp)
    for f in [list_file, master]:
        if os.path.exists(f): os.remove(f)
    return output_path, title


def get_youtube():
    creds = Credentials(token=None, refresh_token=YT_REFRESH_TOKEN,
                        client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET,
                        token_uri="https://oauth2.googleapis.com/token")
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def upload(youtube, path, title, theme):
    description = (
        f"韓国ドラマでよく聞くタイプのフレーズ集（{theme}）。\n"
        "ハングル＋カタカナ発音＋和訳つき。推し活・ドラマのお供に聞き流しでどうぞ。\n"
        "※オリジナルの汎用フレーズで、特定作品のセリフではありません。\n\n"
        "#韓国語 #韓国ドラマ #ハングル #韓国語勉強 #推し活 #shorts #Shorts"
    )
    body = {
        "snippet": {
            "title": (title + " #shorts")[:100],
            "description": description[:5000],
            "tags": ["韓国語", "韓国ドラマ", "ハングル", "韓国語勉強", "韓国語フレーズ",
                     "推し活", "韓国語聞き流し", "Shorts"],
            "categoryId": "27",
            "defaultLanguage": "ja",
        },
        "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(path, chunksize=10 * 1024 * 1024, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None; retry = 0
    while response is None:
        try:
            status, response = req.next_chunk()
            if status: print(f"  up {int(status.progress()*100)}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504):
                retry += 1
                if retry > 10: raise
                time.sleep(min(2 ** retry, 60))
            else:
                raise
    return response


def main():
    log = load_log()
    avoid = [e.get("theme", "") for e in log][-AVOID_RECENT:]
    print("フレーズ生成中...")
    data = generate_phrases(avoid)
    print(f"  テーマ:{data.get('theme')} / {len(data.get('phrases', []))}フレーズ")
    path, title = build_video(data)
    print(f"done: {path}")
    youtube = get_youtube()
    res = upload(youtube, path, title, data.get("theme", ""))
    print(f"uploaded: https://www.youtube.com/watch?v={res['id']}")
    log.append({"theme": data.get("theme", ""), "youtube_title": data.get("youtube_title", "")})
    save_log(log)
    print(f"log: {len(log)} items")


if __name__ == "__main__":
    main()
