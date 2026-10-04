"""Signed video upload to Cloudinary; no tokens or media in the repository."""
import hashlib
import json
import mimetypes
import time
import uuid
from urllib.request import Request, urlopen


def upload_video(path, cloud_name, api_key, api_secret):
    timestamp = str(int(time.time()))
    signature = hashlib.sha1(("timestamp=" + timestamp + api_secret).encode()).hexdigest()
    boundary = "----ZunoLoop" + uuid.uuid4().hex

    def field(name, value):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\""
                f"\r\n\r\n{value}\r\n").encode()

    body = b"".join(field(k, v) for k, v in {
        "timestamp": timestamp, "api_key": api_key, "signature": signature
    }.items())
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: "
             f"{mimetypes.guess_type(path.name)[0] or 'video/mp4'}\r\n\r\n").encode()
    body += path.read_bytes() + b"\r\n" + f"--{boundary}--\r\n".encode()
    request = Request(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/video/upload",
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    url = result.get("secure_url", "")
    if not url.startswith("https://"):
        raise RuntimeError("Cloudinary did not return a public HTTPS video URL")
    return url
