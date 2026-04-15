"""Camera capture via OpenCV for the vision mode."""

import logging

logger = logging.getLogger(__name__)


class CameraManager:
    """OpenCV camera wrapper. Captures JPEG frames for Gemini vision input."""

    def __init__(self, mock: bool = False, device: int = 0):
        self._mock = mock
        self._device = device
        self._cap = None
        self._show_preview = mock  # Show preview window in mock mode.

        try:
            import cv2
            self._cv2 = cv2
            self._cap = cv2.VideoCapture(device)
            if not self._cap.isOpened():
                logger.error("Failed to open camera device %d", device)
                self._cap = None
            else:
                logger.info("Camera opened: device %d", device)
        except ImportError:
            self._cv2 = None
            logger.error("OpenCV not available")
        except Exception as exc:
            self._cv2 = None
            logger.error("Camera init failed: %s", exc)

    def capture_frame(self) -> bytes | None:
        """Capture a single JPEG frame."""
        if self._cap is None:
            return self._synthetic_frame()

        cv2 = self._cv2
        ret, frame = self._cap.read()
        if not ret:
            logger.warning("Failed to capture frame")
            return None

        frame = cv2.resize(frame, (640, 480))

        # Show preview window in mock mode.
        if self._show_preview:
            cv2.imshow("pupper-talk camera", frame)
            cv2.waitKey(1)

        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return jpeg.tobytes()

    def _synthetic_frame(self) -> bytes:
        """Generate a synthetic JPEG frame for when camera is unavailable."""
        import io
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (640, 480), color=(40, 40, 60))
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 590, 430], outline=(0, 200, 200), width=3)
        draw.ellipse([250, 170, 390, 310], fill=(200, 100, 50))
        draw.text((160, 360), "Mock Camera Frame", fill=(255, 255, 255))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return buf.getvalue()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            if self._show_preview and self._cv2:
                self._cv2.destroyAllWindows()
            logger.info("Camera released")
