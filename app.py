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
        "C:/Windows/Fonts/impact.ttf",
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=int(size))
            except OSError:
                pass
    return ImageFont.load_default()


def generate_bokeh_3d_captcha(code_text, width=320, height=130):
    """Generate a dark glossy bokeh scene with clear 3D-style numbers and reflection."""
    # 1. Dark atmospheric gradient background
    bg = Image.new("RGB", (width, height), (8, 15, 28))
    draw_bg = ImageDraw.Draw(bg)

    palette_choices = [
        ((7, 15, 28), (16, 36, 58)),
        ((10, 14, 26), (22, 42, 64)),
        ((8, 18, 30), (14, 46, 62)),
    ]
    top_col, mid_col = random.choice(palette_choices)
    floor_y = int(height * 0.76)

    for y in range(floor_y):
        ratio = y / max(floor_y - 1, 1)
        r = int(top_col[0] * (1 - ratio) + mid_col[0] * ratio)
        g = int(top_col[1] * (1 - ratio) + mid_col[1] * ratio)
        b = int(top_col[2] * (1 - ratio) + mid_col[2] * ratio)
        draw_bg.line([(0, y), (width, y)], fill=(r, g, b))

    # 2. Glowing bokeh circles in the background (blurred for depth)
    bokeh_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_bokeh = ImageDraw.Draw(bokeh_layer)
    bokeh_colors = [
        (56, 189, 248, 135),   # Cyan glow
        (251, 191, 36, 125),   # Warm gold glow
        (147, 197, 253, 110),  # Soft blue glow
        (253, 224, 71, 95),    # Light amber glow
    ]

    for _ in range(random.randint(14, 22)):
        bx = random.randint(0, width)
        by = random.randint(6, floor_y - 4)
        rad = random.randint(5, 16)
        col = random.choice(bokeh_colors)
        draw_bokeh.ellipse([bx - rad, by - rad, bx + rad, by + rad], fill=col)

    bokeh_blurred = bokeh_layer.filter(ImageFilter.GaussianBlur(radius=4.5))
    bg_rgba = bg.convert("RGBA")
    scene = Image.alpha_composite(bg_rgba, bokeh_blurred)

    # 3. Glossy dark reflective floor
    draw_scene = ImageDraw.Draw(scene)
    for y in range(floor_y, height):
        ratio = (y - floor_y) / max(height - floor_y - 1, 1)
        r = int(14 * (1 - ratio) + 5 * ratio)
        g = int(24 * (1 - ratio) + 9 * ratio)
        b = int(38 * (1 - ratio) + 16 * ratio)
        draw_scene.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Subtle floor horizon and perspective grid lines
    draw_scene.line([(0, floor_y), (width, floor_y)], fill=(70, 110, 150, 90), width=1)
    draw_scene.line([(0, int(height * 0.90)), (width, int(height * 0.87))], fill=(55, 85, 120, 75), width=1)

    # 4. Render 3D-extruded crisp digits on a transparent layer
    font = load_font(62)
    text_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_text = ImageDraw.Draw(text_layer)

    # Calculate total width to center the 4 digits cleanly
    spacing = 6
    char_widths = []
    for ch in code_text:
        bbox = draw_text.textbbox((0, 0), ch, font=font)
        char_widths.append(bbox[2] - bbox[0])

    total_w = sum(char_widths) + spacing * (len(code_text) - 1)
    start_x = max(16, (width - total_w) // 2)
    base_y = int(floor_y - 64)

    curr_x = start_x
    for idx, ch in enumerate(code_text):
        # Slight vertical/horizontal variation so bots cannot use fixed pixel masks
        ox = curr_x + random.randint(-2, 2)
        oy = base_y + random.randint(-3, 2)

        # 3D side extrusion (dark metallic depth)
        depth_steps = 6
        for d in range(depth_steps, 0, -1):
            shade = 95 + d * 12
            draw_text.text((ox - d, oy + d // 2), ch, font=font, fill=(shade, shade + 4, shade + 12, 255))

        # Warm rim highlight
        draw_text.text((ox + 1, oy - 1), ch, font=font, fill=(255, 245, 220, 255))

        # Crisp front white face
        draw_text.text((ox, oy), ch, font=font, fill=(248, 250, 252, 255))

        curr_x += char_widths[idx] + spacing

    # 5. Create soft floor reflection beneath the digits
    reflection = text_layer.crop((0, int(floor_y - 58), width, floor_y + 4))
    reflection = reflection.transpose(Image.FLIP_TOP_BOTTOM)
    reflection = reflection.filter(ImageFilter.GaussianBlur(radius=2.5))

    # Fade reflection alpha
    r_chan, g_chan, b_chan, a_chan = reflection.split()
    a_chan = a_chan.point(lambda p: int(p * 0.26))
    reflection = Image.merge("RGBA", (r_chan, g_chan, b_chan, a_chan))

    scene.paste(reflection, (0, floor_y + 1), reflection)
    scene = Image.alpha_composite(scene, text_layer)

    final_img = scene.convert("RGB")
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

        image_base64 = generate_bokeh_3d_captcha(code)

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
