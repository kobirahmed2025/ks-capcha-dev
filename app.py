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


def random_color(low=40, high=220):
    low_i = max(0, min(255, int(low)))
    high_i = max(low_i, min(255, int(high)))
    return (
        int(random.randint(low_i, high_i)),
        int(random.randint(low_i, high_i)),
        int(random.randint(low_i, high_i)),
    )


def load_font(size):
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=int(size))
            except OSError:
                pass
    return ImageFont.load_default()


def generate_captcha_image(code_text, width=220, height=80):
    width = int(width)
    height = int(height)

    bg_start = random_color(170, 245)
    bg_end = random_color(140, 230)
    image = Image.new("RGB", (width, height), bg_start)
    draw = ImageDraw.Draw(image)

    # Gradient background rows
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(bg_start[0] * (1 - ratio) + bg_end[0] * ratio)
        g = int(bg_start[1] * (1 - ratio) + bg_end[1] * ratio)
        b = int(bg_start[2] * (1 - ratio) + bg_end[2] * ratio)
        draw.line([(0, y), (width - 1, y)], fill=(r, g, b))

    # Random circles
    for _ in range(random.randint(5, 10)):
        cx = random.randint(0, width - 1)
        cy = random.randint(0, height - 1)
        radius = random.randint(8, 24)
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        draw.ellipse(bbox, outline=random_color(50, 210), width=random.randint(1, 2))

    # Random lines
    for _ in range(random.randint(6, 12)):
        x1 = random.randint(0, width - 1)
        y1 = random.randint(0, height - 1)
        x2 = random.randint(0, width - 1)
        y2 = random.randint(0, height - 1)
        draw.line([(x1, y1), (x2, y2)], fill=random_color(30, 200), width=random.randint(1, 2))

    # Random dots
    for _ in range(random.randint(35, 70)):
        dx = random.randint(0, width - 1)
        dy = random.randint(0, height - 1)
        draw.point((dx, dy), fill=random_color(20, 230))

    # Draw 4 rotated digits
    font = load_font(34)
    slot_width = max(1, width // max(len(code_text), 1))

    for idx, ch in enumerate(code_text):
        char_layer = Image.new("RGBA", (60, 64), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_layer)
        digit_color = random_color(10, 110)
        char_draw.text((12, 8), ch, font=font, fill=digit_color)

        angle = random.randint(-25, 25)
        rotated = char_layer.rotate(angle, resample=Image.BICUBIC, expand=True)

        max_x = max(0, width - rotated.width)
        max_y = max(0, height - rotated.height)
        desired_x = idx * slot_width + random.randint(0, max(0, slot_width - 20))
        pos_x = max(0, min(int(desired_x), max_x))
        pos_y = max(0, min(int(random.randint(2, max(2, height - 30))), max_y))

        image.paste(rotated, (pos_x, pos_y), rotated)

    # Foreground noise
    for _ in range(random.randint(150, 280)):
        nx = random.randint(0, width - 1)
        ny = random.randint(0, height - 1)
        image.putpixel((nx, ny), random_color(0, 255))

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
        code = "".join(random.choices(string.digits, k=4))
        expires_at = time.time() + CAPTCHA_TTL_SECONDS

        captcha_store[captcha_id] = {
            "code": code,
            "expires_at": expires_at,
        }

        image_base64 = generate_captcha_image(code)

        return jsonify({
            "captcha_id": captcha_id,
            "image_base64": image_base64,
            "expires_in_seconds": CAPTCHA_TTL_SECONDS,
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": str(e),
        }), 500


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
