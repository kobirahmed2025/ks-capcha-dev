import base64
import io
import os
import random
import string
import time
import uuid
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
# Enable CORS for all origins and routes
CORS(app, resources={r"/*": {"origins": "*"}})

# Server memory store: { captcha_id: {"code": "4792", "expires_at": 1700000000.0} }
captcha_store = {}
CAPTCHA_TTL_SECONDS = 120  # 2 minutes


def cleanup_expired_captchas():
    """Remove expired CAPTCHA entries from server memory."""
    now = time.time()
    expired_ids = [
        cid for cid, entry in captcha_store.items()
        if entry["expires_at"] <= now
    ]
    for cid in expired_ids:
        del captcha_store[cid]


def random_color(low=40, high=220):
    """Return a random RGB tuple."""
    return (
        random.randint(low, high),
        random.randint(low, high),
        random.randint(low, high),
    )


def load_font(size):
    """Try loading a TrueType font if available; fall back to default bitmap font."""
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def generate_captcha_image(code_text, width=220, height=80):
    """Generate a colorful CAPTCHA image with noise, shapes, and rotated digits."""
    # Create base image with a vibrant random background color
    bg_start = random_color(170, 245)
    bg_end = random_color(140, 230)
    image = Image.new("RGB", (width, height), bg_start)
    draw = ImageDraw.Draw(image)

    # Subtle horizontal gradient / color bands
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(bg_start[0] * (1 - ratio) + bg_end[0] * ratio)
        g = int(bg_start[1] * (1 - ratio) + bg_end[1] * ratio)
        b = int(bg_start[2] * (1 - ratio) + bg_end[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Random background circles
    for _ in range(random.randint(5, 10)):
        cx = random.randint(-10, width + 10)
        cy = random.randint(-10, height + 10)
        radius = random.randint(8, 28)
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        draw.ellipse(bbox, outline=random_color(50, 210), width=random.randint(1, 2))

    # Random lines across the image
    for _ in range(random.randint(6, 12)):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=random_color(30, 200), width=random.randint(1, 2))

    # Random dots
    for _ in range(random.randint(35, 70)):
        dx = random.randint(0, width - 1)
        dy = random.randint(0, height - 1)
        draw.point((dx, dy), fill=random_color(20, 230))

    # Draw each of the 4 digits with random position, color, and slight rotation
    font = load_font(34)
    slot_width = width // len(code_text)

    for idx, ch in enumerate(code_text):
        # Create a small transparent layer per character so it can be rotated cleanly
        char_layer = Image.new("RGBA", (54, 58), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_layer)
        digit_color = random_color(10, 120)
        char_draw.text((10, 6), ch, font=font, fill=digit_color)

        angle = random.randint(-28, 28)
        rotated = char_layer.rotate(angle, resample=Image.BICUBIC, expand=True)

        base_x = idx * slot_width + random.randint(2, max(3, slot_width - 36))
        base_y = random.randint(4, max(5, height - rotated.height - 6))
        base_x = max(2, min(base_x, width - rotated.width - 2))
        base_y = max(2, min(base_y, height - rotated.height - 2))

        image.paste(rotated, (base_x, base_y), rotated)

    # Foreground pixel noise on top
    noise_count = random.randint(180, 320)
    for _ in range(noise_count):
        nx = random.randint(0, width - 1)
        ny = random.randint(0, height - 1)
        image.putpixel((nx, ny), random_color(0, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


@app.route("/", methods=["GET"])
def home():
    """Serve the interactive CAPTCHA demo page."""
    return render_template("index.html")


@app.route("/captcha", methods=["GET"])
def get_captcha():
    """Generate a new 4-digit CAPTCHA image and store it for 2 minutes."""
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


@app.route("/verify-captcha", methods=["POST"])
def verify_captcha():
    """Verify { captcha_id, user_input } against stored code before expiry."""
    cleanup_expired_captchas()

    payload = request.get_json(silent=True) or {}
    captcha_id = str(payload.get("captcha_id") or "").strip()
    user_input = str(payload.get("user_input") or "").strip()

    if not captcha_id or not user_input:
        return jsonify({
            "success": False,
            "message": "Wrong captcha",
        }), 400

    record = captcha_store.get(captcha_id)
    if not record:
        return jsonify({
            "success": False,
            "message": "Wrong captcha",
        }), 400

    # Check expiry explicitly
    if time.time() > record["expires_at"]:
        del captcha_store[captcha_id]
        return jsonify({
            "success": False,
            "message": "Wrong captcha",
        }), 400

    expected_code = record["code"]
    # Consume CAPTCHA after a verification attempt so it cannot be replayed
    del captcha_store[captcha_id]

    if user_input == expected_code:
        return jsonify({
            "success": True,
        }), 200

    return jsonify({
        "success": False,
        "message": "Wrong captcha",
    }), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
