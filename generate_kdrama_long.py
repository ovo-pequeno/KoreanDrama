# =========================================================
# 韓国ドラマ頻出フレーズ聞き流し｜長尺（ミニ会話劇）
# 2人の短い会話を複数シーン。各セリフ ハングル＋カタカナ＋和訳＋話者ラベル。
# 話者はgTTS(ko)1声、画面のA/B名前ラベル＋色で区別。8分超え・15分以内。
# 【完全創作・汎用】実在ドラマ名/俳優名/実セリフは使わない。
# Gemini → gTTS(ko) → MoviePy → YouTube API / 横型1920x1080
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
NUM_SCENES   = int(os.environ.get("NUM_SCENES", "10"))   # 会話シーン（場面）数
MAX_SECONDS  = 14 * 60
OUT_DIR  = "out_l"
TMP_DIR  = "tmp_l"
LOG_PATH = "used_log_kdrama_long.json"
AVOID_RECENT = 40

BG_IMAGE = "assets/bg_long.png" if os.path.exists("assets/bg_long.png") else None
BG_COLOR = (30, 18, 34)
BGM_PATH = "assets/bgm.mp3" if os.path.exists("assets/bgm.mp3") else None
BGM_VOLUME = 0.10

client = genai.Client(api_key=GEMINI_API_KEY)

W, H = 1920, 1080
FPS = 10

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
TEXT_COLOR = "white"
KANA_COLOR = "#FFD27F"
JA_COLOR   = "#7FC0FF"
STROKE_COLOR = "#000000"
# 話者A/Bをラベル色で区別（声は同じgTTS韓国語）
SPEAKER_COLORS = {"A": "#FF9EC4", "B": "#8FD0FF"}
HANGUL_FS  = 74
KANA_FS    = 44
JA_FS      = 44
LABEL_FS   = 40
HEADER_FS  = 34
HEADER_TEXT = "ドラマ韓国語 会話"


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


def generate_dialogue(avoid_summaries, max_retries=5):
    models = [MODEL, "gemini-2.5-flash-lite", "gemini-3.1-flash-lite"]
    avoid_text = ""
    if avoid_summaries:
        joined = "\n".join(f"- {s}" for s in avoid_summaries)
        avoid_text = f"\n\n【これらと被らない別の場面設定にする】\n{joined}"
    prompt = f"""あなたは韓国語の先生で、韓流ドラマ好きの日本人初心者向けに
「ドラマのワンシーン風のミニ会話劇」を作ります。

重要な制約：
- 実在のドラマ名・俳優名・アイドル名・実際のセリフは一切使わない。
- あくまで「ドラマにありがちな“汎用的な”場面と会話」を自分で創作する。
- 登場人物は2人（AとB）。名前は使わず役割で（例：先輩と後輩、恋人同士、店員と客 など）。
- 初心者向けに、短くて実用的なセリフにする。

1つの会話は6〜10往復程度。各セリフに「話者(A/B)」「ハングル」「カタカナ発音」「日本語訳」を付ける。
カタカナ発音は日本人が読めるように自然なカタカナで。

以下のJSON形式のみで出力（前後に説明・マークダウン不要）:
{{
  "situation_ja": "この会話の場面設定（日本語・20文字以内・例：カフェで先輩と）",
  "title_ja": "日本語タイトル（25文字以内・被り防止ログ用）",
  "lines": [
    {{"speaker": "A", "hangul": "ハングル", "kana": "カタカナ発音", "ja": "日本語訳"}}
  ]
}}
※linesは6〜10行。speakerはAかB。{avoid_text}
"""
    cfg = genai_types.GenerateContentConfig(max_output_tokens=4096, temperature=1.1) if genai_types else None
    for attempt in range(max_retries):
        m = models[min(attempt, len(models) - 1)]
        try:
            if cfg:
                resp = client.models.generate_content(model=m, contents=prompt, config=cfg)
            else:
                resp = client.models.generate_content(model=m, contents=prompt)
            text = resp.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(text)
            if not data.get("lines"):
                raise ValueError("linesが空")
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
        combined = normal + AudioSegment.silent(duration=450) + slow + AudioSegment.silent(duration=400)
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
        size = (W - 300, None)
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


def make_line_scene(speaker, hangul, kana, ja, audio_file, situation):
    narration = AudioFileClip(audio_file)
    duration = narration.duration + 0.4
    layers = [make_bg(duration)]
    # ヘッダー（場面）
    layers.append(make_outlined(f"{HEADER_TEXT}　- {situation} -", duration, HEADER_FS,
                                 "#E7A8FF", stroke_w=4, ypos=int(H * 0.06)))
    # 話者ラベル（色で区別）
    spk_color = SPEAKER_COLORS.get(speaker, "#FFFFFF")
    layers.append(make_outlined(f"{speaker}", duration, LABEL_FS, spk_color,
                                 stroke_w=6, ypos=int(H * 0.24), size=(200, None)))
    # ハングル・カナ・和訳
    layers.append(make_outlined(hangul, duration, HANGUL_FS, TEXT_COLOR,
                                 stroke_w=9, ypos=int(H * 0.40)))
    layers.append(make_outlined(kana, duration, KANA_FS, KANA_COLOR,
                                 stroke_w=7, ypos=int(H * 0.62)))
    layers.append(make_outlined(ja, duration, JA_FS, JA_COLOR,
                                 stroke_w=7, ypos=int(H * 0.74)))
    scene = CompositeVideoClip(layers, size=(W, H)).set_duration(duration)
    if duration > narration.duration + 0.02:
        narration = CompositeAudioClip([narration]).set_duration(duration)
    return scene.set_audio(narration)


def make_card(text, audio_file):
    narration = AudioFileClip(audio_file)
    duration = narration.duration + 0.8
    layers = [ColorClip(size=(W, H), color=(20, 12, 24), duration=duration)]
    layers.append(make_outlined(text, duration, 70, "white", stroke_w=7, ypos="center"))
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


def _dur(path):
    c = AudioFileClip(path); d = c.duration; c.close(); return d


def build_video(dialogues):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)
    main_title = dialogues[0].get("title_ja", "ドラマ韓国語 会話")
    safe = main_title
    for ch in r'\/:*?"<>|':
        safe = safe.replace(ch, "")
    output_path = os.path.join(OUT_DIR, f"{safe.strip()[:60]}.mp4")

    clip_paths = []
    idx = 0
    total = 0.0
    used = 0
    for di, dlg in enumerate(dialogues):
        situation = dlg.get("situation_ja", "会話")
        scene_clips = []
        scene_dur = 0.0
        local_idx = idx
        # 場面タイトルカード
        card_txt = f"場面 {di+1}\n{situation}"
        a = make_audio_ko(situation, f"a_{local_idx}.mp3", repeat=False)
        cd = _dur(a) + 0.8
        p = f"{TMP_DIR}/clip_{local_idx:04d}.mp4"
        render(make_card(card_txt, a), p)
        os.remove(a); scene_clips.append(p); scene_dur += cd; local_idx += 1
        # 各セリフ
        for ln in dlg["lines"]:
            spk = ln.get("speaker", "A")
            hangul = (ln.get("hangul") or "").strip()
            kana = (ln.get("kana") or "").strip()
            ja = (ln.get("ja") or "").strip()
            if not hangul:
                continue
            print(f"  [場面{di+1} {spk}] {hangul}")
            a = make_audio_ko(hangul, f"a_{local_idx}.mp3", repeat=True)
            sd = _dur(a) + 0.4
            p = f"{TMP_DIR}/clip_{local_idx:04d}.mp4"
            render(make_line_scene(spk, hangul, kana, ja, a, situation), p)
            os.remove(a); scene_clips.append(p); scene_dur += sd; local_idx += 1
        # 場面まるごと入れて上限超えなら不採用で打ち切り（常に場面完結で終わる）
        if used > 0 and total + scene_dur > MAX_SECONDS:
            for cp in scene_clips:
                if os.path.exists(cp): os.remove(cp)
            break
        clip_paths.extend(scene_clips)
        total += scene_dur
        idx = local_idx
        used += 1

    # エンディング
    a = make_audio_ko("오늘도 수고하셨습니다", f"a_{idx}.mp3", repeat=False)
    p = f"{TMP_DIR}/clip_{idx:04d}.mp4"
    render(make_card("오늘도 수고하셨습니다！\nまた次回の会話で！", a), p)
    clip_paths.append(p); os.remove(a); idx += 1

    print(f"  connect {len(clip_paths)} scenes (~{int(total)}s)...")
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
    return output_path, main_title, used


def get_youtube():
    creds = Credentials(token=None, refresh_token=YT_REFRESH_TOKEN,
                        client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET,
                        token_uri="https://oauth2.googleapis.com/token")
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def upload(youtube, path, title, dialogues):
    sits = "／".join(d.get("situation_ja", "") for d in dialogues)
    description = (
        "韓国ドラマ風のミニ会話劇で学ぶ韓国語（ハングル＋カタカナ発音＋和訳）。\n"
        "推し活・ドラマのお供に、聞き流しでフレーズを覚えよう。\n"
        "※オリジナルの汎用会話で、特定作品のセリフではありません。\n"
        f"場面：{sits}\n\n"
        "#韓国語 #韓国ドラマ #ハングル #韓国語勉強 #推し活 #韓国語聞き流し #韓国語会話"
    )
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["韓国語", "韓国ドラマ", "ハングル", "韓国語勉強", "韓国語会話",
                     "推し活", "韓国語聞き流し", "作業用BGM"],
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
    avoid = [e.get("title_ja", "") for e in log][-AVOID_RECENT:]
    dialogues = []
    for i in range(NUM_SCENES):
        print(f"会話 {i+1}/{NUM_SCENES} 生成中...")
        d = generate_dialogue(avoid + [x.get("title_ja", "") for x in dialogues])
        dialogues.append(d)
        print(f"  {d.get('situation_ja')} ({len(d.get('lines', []))}行)")
        time.sleep(2)

    path, title, used = build_video(dialogues)
    used_dialogues = dialogues[:used] if used else dialogues
    print(f"done: {path} (使用 {used}会話)")
    youtube = get_youtube()
    res = upload(youtube, path, title, used_dialogues)
    print(f"uploaded: https://www.youtube.com/watch?v={res['id']}")
    for d in used_dialogues:
        log.append({"title_ja": d.get("title_ja", ""), "situation_ja": d.get("situation_ja", "")})
    save_log(log)
    print(f"log: {len(log)} items")


if __name__ == "__main__":
    main()
