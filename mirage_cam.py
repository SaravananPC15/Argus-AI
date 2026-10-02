"""
mirage_cam.py — Protocol Mirage Cam (Encrypted Space Feed).

Streams the laptop's webcam to the phone dashboard as MJPEG, the same
pattern remote_server.py already uses for the screen-share feed
(screen_stream_generator). "Encrypted" here means two real things,
honestly scoped:

1. Access control: the feed is only servable through remote_server.py's
   session, which — once Protocol Gatekeeper (gatekeeper.py) is enabled —
   requires MFA-verified session auth. Without that, anyone who can reach
   your LAN IP:port can hit the endpoint, same as any other route on this
   server.
2. Wire encryption: actual encryption-in-transit means TLS. This module
   doesn't invent its own crypto for a video stream (rolling your own is
   a bad idea); instead see SETUP.md for generating a self-signed cert
   and pointing uvicorn at it via --ssl-keyfile/--ssl-certfile, which
   covers every route this server serves, not just this one.
"""

import cv2
import time

_camera = None


def _get_camera():
    global _camera
    if _camera is None:
        _camera = cv2.VideoCapture(0)
    return _camera


def release_camera():
    global _camera
    if _camera is not None:
        _camera.release()
        _camera = None


def camera_stream_generator(quality: int = 70, target_fps: int = 12):
    """Generator yielding multipart JPEG frames for a StreamingResponse,
    matching remote_server.py's existing screen_stream_generator pattern."""
    camera = _get_camera()
    frame_interval = 1.0 / target_fps

    while True:
        try:
            import feature_toggles
            if not feature_toggles.is_enabled("mirage_cam"):
                time.sleep(1)
                continue
        except Exception:
            pass

        success, frame = camera.read()
        if not success:
            time.sleep(0.5)
            continue

        ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            continue

        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

        time.sleep(frame_interval)
