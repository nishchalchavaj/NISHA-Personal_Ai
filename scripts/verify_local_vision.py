"""Describe a synthetic image with installed local vision weights; no remote images."""

from io import BytesIO

from PIL import Image, ImageDraw

from nisha.settings import load_settings
from nisha.vision import LocalVision


def main():
    settings = load_settings()
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 100, 230, 260), fill="red")
    draw.rectangle((370, 100, 530, 260), fill="blue")
    data = BytesIO()
    image.save(data, format="PNG")
    caption = LocalVision(settings.ollama_url, settings.vision_model).describe(data.getvalue())
    value = caption.casefold()
    print("Actual local image description:", caption, flush=True)
    assert "red" in value and "blue" in value, caption
    assert any(word in value for word in ("circle", "circular", "round", "ball")), caption
    assert any(word in value for word in ("square", "rectangle", "rectangular", "box")), caption
    print(
        "PASS: installed local vision model identified the synthetic objects and colors. No image sent outside this PC."
    )


if __name__ == "__main__":
    main()
