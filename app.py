import base64
import io
import os
import random
import string
import time
import traceback
import uuid
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFilter, ImageFont

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

captcha_store = {}
CAPTCHA_TTL_SECONDS = 120


def cleanup_expired_captchas():
    now = time.time()
    expired_ids = [
        cid for cid, entry in captcha_store.items()
        if entry["expires_at"] <= now
    ]
    for cid in expired_ids:
        del captcha_store[cid]


def load_font(size):
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=int(size))
            except OSError:
                pass
    return ImageFont.load_default()


def generate_black_white_captcha(code_text, width=300, height=110):
    """Generate a clean black background with crisp white 4-digit text."""
    # Pure black background
    image = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)

    # Subtle dark-gray decorative lines and dots (low contrast so text stays crystal clear)
    for _ in range(random.randint(3, 6)):
        x1 = random.randint(0, width - 1)
        y1 = random.randint(0, height - 1)
        x2 = random.randint(0, width - 1)
        y2 = random.randint(0, height - 1)
        shade = random.randint(25, 55)
        draw.line([(x1, y1), (x2, y2)], fill=(shade, shade, shade, 255), width=1)

    for _ in range(random.randint(20, 40)):
        dx = random.randint(0, width - 1)
        dy = random.randint(0, height - 1)
        shade = random.randint(35, 75)
        draw.point((dx, dy), fill=(shade, shade, shade, 255))

    # Draw clear white digits with slight tilt and spacing
    font = load_font(56)
    char_boxes = []
    spacing = 12

    for ch in code_text:
        bbox = draw.textbbox((0, 0), ch, font=font)
        cw = bbox[2] - bbox[0]
        ch_h = bbox[3] - bbox[1]
        char_boxes.append((ch, cw, ch_h))

    total_width = sum(item[1] for item in char_boxes) + spacing * (len(char_boxes) - 1)
    cursor_x = max(12, (width - total_width) // 2)
    center_y = height // 2

    for ch, cw, ch_h in char_boxes:
        layer_w = max(64, cw + 28)
        layer_h = max(72, ch_h + 28)
        char_layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_layer)

        lx = (layer_w - cw) // 2
        ly = (layer_h - ch_h) // 2

        # Soft dark outline for clean separation
        for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            char_draw.text((lx + ox, ly + oy), ch, font=font, fill=(0, 0, 0, 255))

        # Crisp white text
        char_draw.text((lx, ly), ch, font=font, fill=(255, 255, 255, 255))

        angle = random.randint(-12, 12)
        rotated = char_layer.rotate(angle, resample=Image.BICUBIC, expand=True)

        paste_x = int(cursor_x + (cw - rotated.width) // 2 + random.randint(-2, 2))
        paste_y = int(center_y - rotated.height // 2 + random.randint(-4, 4))

        paste_x = max(0, min(paste_x, width - rotated.width))
        paste_y = max(0, min(paste_y, height - rotated.height))

        image.paste(rotated, (paste_x, paste_y), rotated)
        cursor_x += cw + spacing

    final_img = image.convert("RGB")
    buffer = io.BytesIO()
    final_img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


@app.route("/", methods=["GET"])
def home():
    try:
        return render_template("index.html")
    except Exception:
        traceback.print_exc()
        return jsonify({"success": False, "message": "Template index.html not found"}), 500


@app.route("/captcha", methods=["GET"])
def get_captcha():
    try:
        cleanup_expired_captchas()
        captcha_id = str(uuid.uuid4())
        code = "".join(random.choices(string.digits, k=4))
        expires_at = time.time() + CAPTCHA_TTL_SECONDS

        captcha_store[captcha_id] = {
            "code": code,
            "expires_at": expires_at,
        }

        image_base64 = generate_black_white_captcha(code)

        return jsonify({
            "captcha_id": captcha_id,
            "image_base64": image_base64,
            "expires_in_seconds": CAPTCHA_TTL_SECONDS,
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/verify-captcha", methods=["POST"])
def verify_captcha():
    try:
        cleanup_expired_captchas()
        payload = request.get_json(silent=True) or {}
        captcha_id = str(payload.get("captcha_id") or "").strip()
        user_input = str(payload.get("user_input") or "").strip()

        if not captcha_id or not user_input:
            return jsonify({"success": False, "message": "Wrong captcha"}), 400

        record = captcha_store.get(captcha_id)
        if not record:
            return jsonify({"success": False, "message": "Wrong captcha"}), 400

        if time.time() > record["expires_at"]:
            del captcha_store[captcha_id]
            return jsonify({"success": False, "message": "Wrong captcha"}), 400

        expected_code = record["code"]
        del captcha_store[captcha_id]

        if user_input == expected_code:
            return jsonify({"success": True}), 200

        return jsonify({"success": False, "message": "Wrong captcha"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
