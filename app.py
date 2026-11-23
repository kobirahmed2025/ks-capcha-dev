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
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Server memory store: { captcha_id: {"code": "20719", "expires_at": 1700000000.0} }
captcha_store = {}
CAPTCHA_TTL_SECONDS = 120
CAPTCHA_DIGITS = 5


def cleanup_expired_captchas():
    now = time.time()
    expired_ids = [
        cid for cid, entry in captcha_store.items()
        if entry["expires_at"] <= now
    ]
    for cid in expired_ids:
        del captcha_store[cid]


def load_font(size):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_paths = [
        os.path.join(base_dir, "fonts", "DejaVuSans-Bold.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/impact.ttf",
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=int(size))
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=int(size))
    except TypeError:
        return ImageFont.load_default()


def generate_black_white_captcha(code_text, width=420, height=140):
    """Generate a solid black background with bold, high-contrast white digits."""
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    font = load_font(84)
    spacing = 10
    char_boxes = []

    for ch in code_text:
        bbox = draw.textbbox((0, 0), ch, font=font)
        cw = bbox[2] - bbox[0]
        ch_h = bbox[3] - bbox[1]
        char_boxes.append((ch, cw, ch_h, bbox[0], bbox[1]))

    total_width = sum(item[1] for item in char_boxes) + spacing * (len(char_boxes) - 1)
    cursor_x = max(16, (width - total_width) // 2)
    center_y = height // 2

    for ch, cw, ch_h, off_x, off_y in char_boxes:
        px = cursor_x - off_x
        py = center_y - (ch_h // 2) - off_y
        draw.text((px, py), ch, font=font, fill=(255, 255, 255))
        cursor_x += cw + spacing

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
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
        code = "".join(random.choices(string.digits, k=CAPTCHA_DIGITS))
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
            return jsonify({"success": False, "message": "Captcha expired"}), 400

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
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
