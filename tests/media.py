"""Образцы файлов для тестов раздаток: настоящие картинки и звук, минимальные PDF и заготовки аудио."""
import io
import wave

from PIL import Image

HTML = "<!doctype html><html><body><h1>Страница</h1></body></html>".encode()


def png_bytes(size=(40, 20), color=(200, 30, 30), mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, "PNG")
    return out.getvalue()


def jpeg_with_exif(size=(40, 20)):
    """Широкий кадр с «секретной» меткой камеры и поворотом: после обработки метка исчезает, а поворот применён."""
    exif = Image.Exif()
    exif[0x010F] = "SecretMakerXYZ"
    exif[0x0112] = 6
    out = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(out, "JPEG", exif=exif)
    return out.getvalue()


def gif_animated():
    frames = [Image.new("P", (16, 16), i * 40) for i in range(3)]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=50, loop=0)
    return out.getvalue()


def webp_bytes():
    out = io.BytesIO()
    Image.new("RGB", (30, 30), (0, 90, 40)).save(out, "WEBP")
    return out.getvalue()


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return out.getvalue()


MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 400
MP3_RAW = b"\xff\xfb\x90\x00" + b"\x00" * 400
OGG = b"OggS\x00\x02" + b"\x00" * 300
FLAC = b"fLaC\x00\x00\x00\x22" + b"\x00" * 300
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A mp42isom" + b"\x00" * 300
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 300
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
