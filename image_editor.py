"""
画像加工モジュール

ピクセル調整・顔モザイク: Pillow + OpenCV（ローカル）
服の色変更・ポーズ変更: Replicate Flux Kontext Pro
"""
import io
import os
import logging
import requests

logger = logging.getLogger(__name__)

REPLICATE_MODEL = "black-forest-labs/flux-kontext-pro"


# ─── ローカル処理 ──────────────────────────────────────────────────────────────

def pixel_adjust(image_bytes: bytes, width: int, height: int) -> bytes:
    """リサイズ（ピクセル調整）"""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = img.resize((width, height), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def face_mosaic(image_bytes: bytes, block_size: int = 15) -> tuple[bytes, int]:
    """顔検出してモザイク。(処理後bytes, 検出顔数) を返す。"""
    import cv2
    import numpy as np

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("画像の読み込みに失敗しました")

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

    for (x, y, w, h) in faces:
        roi = img[y:y + h, x:x + w]
        small = cv2.resize(roi, (max(1, w // block_size), max(1, h // block_size)))
        img[y:y + h, x:x + w] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return bytes(buf), len(faces)


# ─── Replicate 処理 ────────────────────────────────────────────────────────────

def _replicate_edit(image_bytes: bytes, prompt: str) -> bytes:
    """Flux Kontext Pro で画像編集して結果バイト列を返す。"""
    import replicate

    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN が設定されていません")

    client = replicate.Client(api_token=token)
    img_file = io.BytesIO(image_bytes)
    img_file.name = "image.jpg"

    output = client.run(
        REPLICATE_MODEL,
        input={"input_image": img_file, "prompt": prompt},
    )

    # output は URL文字列 or FileOutput or list
    if isinstance(output, list):
        url = str(output[0])
    elif hasattr(output, "url"):
        url = output.url
    else:
        url = str(output)

    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def change_clothing_color(image_bytes: bytes, color: str) -> bytes:
    """服の色を変更する。"""
    prompt = (
        f"Change the color of the clothing/outfit to {color}. "
        "Keep the person's face, hairstyle, body shape, pose, and background exactly the same."
    )
    return _replicate_edit(image_bytes, prompt)


def change_pose(image_bytes: bytes, pose_description: str) -> bytes:
    """ポーズを変更する。"""
    prompt = (
        f"Change the person's pose to: {pose_description}. "
        "Keep the person's appearance, face, hair, clothing, and background exactly the same."
    )
    return _replicate_edit(image_bytes, prompt)
