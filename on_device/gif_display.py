"""Animated GIF display on ST7789 LCD or Pygame window — with hot-swap support.

Also supports Bumblebee eye-rendering mode: when switch_to_eyes() is called,
the display switches from GIF frames to real-time animated Autobot-style eyes.
"""

import logging
import math
import os
import queue
import random
import sys
import threading
import time

import pygame
from PIL import Image

logger = logging.getLogger(__name__)

LCD_WIDTH = 320
LCD_HEIGHT = 240
MOCK_SCALE = 2

# --------------------------------------------------------------------------
# Bumblebee eye constants (from pupper-bumblebee)
# --------------------------------------------------------------------------

EYE_RADIUS = 38
EYE_SPACING = 130
EYE_CENTER_Y = 90
IRIS_RADIUS = 26
PUPIL_RADIUS = 14
GLOW_RADIUS = 52
VISOR_HEIGHT = 12
VISOR_EXTEND = 20
TICK_COUNT = 12
TICK_INNER = 30
TICK_OUTER = 36
TICK_WIDTH = 2
MOUTH_Y = 170
MOUTH_WIDTH = 100
MOUTH_HEIGHT = 40
MOUTH_SEGMENTS = 5
MOUTH_SEG_GAP = 2
MOUTH_CORNER_R = 4
BLINK_INTERVAL_MIN = 3.0
BLINK_INTERVAL_MAX = 5.0
BLINK_DURATION = 0.15

BLACK = (0, 0, 0)

# Bumblebee palette — golden yellow for all moods (shape changes, not color).
_BEE_YELLOW = {
    "glow": (100, 75, 0), "outer": (220, 170, 0), "iris": (255, 210, 0),
    "pupil": (255, 245, 180), "tick": (230, 180, 0), "visor": (70, 50, 0),
    "highlight": (255, 255, 210), "mouth_frame": (110, 80, 0),
    "mouth_seg": (180, 140, 0), "mouth_active": (255, 210, 0),
}

# Sentiment palette — color changes per mood (from pupper-sentiment MOOD_MAP).
_SENTIMENT_COLORS = {
    "neutral": {  # Cyber blue
        "glow": (30, 60, 80), "outer": (0, 140, 200), "iris": (0, 180, 255),
        "pupil": (180, 230, 255), "tick": (0, 160, 220), "visor": (0, 40, 60),
        "highlight": (200, 240, 255), "mouth_frame": (0, 60, 90),
        "mouth_seg": (0, 100, 150), "mouth_active": (0, 180, 255),
    },
    "happy": {  # Energy green
        "glow": (15, 80, 15), "outer": (30, 200, 30), "iris": (50, 255, 50),
        "pupil": (200, 255, 200), "tick": (40, 220, 40), "visor": (10, 50, 10),
        "highlight": (220, 255, 220), "mouth_frame": (20, 80, 20),
        "mouth_seg": (30, 150, 30), "mouth_active": (50, 255, 50),
    },
    "sad": {  # Ice blue-white
        "glow": (70, 80, 85), "outer": (180, 220, 255), "iris": (220, 240, 255),
        "pupil": (240, 248, 255), "tick": (200, 230, 255), "visor": (50, 60, 70),
        "highlight": (250, 252, 255), "mouth_frame": (80, 100, 110),
        "mouth_seg": (140, 170, 200), "mouth_active": (220, 240, 255),
    },
    "angry": {  # Blood red
        "glow": (80, 0, 0), "outer": (180, 0, 0), "iris": (255, 0, 0),
        "pupil": (255, 120, 120), "tick": (200, 0, 0), "visor": (50, 0, 0),
        "highlight": (255, 180, 180), "mouth_frame": (90, 0, 0),
        "mouth_seg": (150, 0, 0), "mouth_active": (255, 30, 30),
    },
    "surprised": {  # Neon teal
        "glow": (30, 80, 65), "outer": (0, 200, 160), "iris": (0, 255, 200),
        "pupil": (180, 255, 240), "tick": (0, 220, 180), "visor": (0, 50, 40),
        "highlight": (200, 255, 245), "mouth_frame": (0, 80, 60),
        "mouth_seg": (0, 140, 110), "mouth_active": (0, 255, 200),
    },
    "curious": {  # Amber yellow
        "glow": (80, 50, 0), "outer": (200, 120, 0), "iris": (255, 160, 0),
        "pupil": (255, 220, 140), "tick": (220, 140, 0), "visor": (50, 30, 0),
        "highlight": (255, 240, 180), "mouth_frame": (90, 55, 0),
        "mouth_seg": (160, 100, 0), "mouth_active": (255, 160, 0),
    },
}

_MOOD_SHAPE = {
    "neutral": {"scale": 1.0, "y_offset": 0, "squash": 1.0, "left_scale": 1.0, "right_scale": 1.0},
    "happy": {"scale": 1.12, "y_offset": -3, "squash": 1.0, "left_scale": 1.0, "right_scale": 1.0},
    "sad": {"scale": 0.88, "y_offset": 8, "squash": 0.85, "left_scale": 1.0, "right_scale": 1.0},
    "angry": {"scale": 0.95, "y_offset": 2, "squash": 0.6, "left_scale": 1.0, "right_scale": 1.0},
    "surprised": {"scale": 1.2, "y_offset": -2, "squash": 1.0, "left_scale": 1.0, "right_scale": 1.0},
    "curious": {"scale": 1.0, "y_offset": 0, "squash": 1.0, "left_scale": 1.15, "right_scale": 0.9},
}


def _lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (int(c1[0]+(c2[0]-c1[0])*t), int(c1[1]+(c2[1]-c1[1])*t), int(c1[2]+(c2[2]-c1[2])*t))


class GifDisplay:
    """Display animated GIFs with runtime switching + Bumblebee eye mode."""

    def __init__(self, gif_path: str | None = None, mock: bool = False, ready_text: str = "Ready"):
        self._mock = mock
        self._ready_text = ready_text
        self._running = False
        self._thread = None
        self._frames: list[pygame.Surface] = []
        self._frame_durations: list[float] = []
        self._swap_queue: queue.Queue[str] = queue.Queue()
        self._current_gif = gif_path

        # Eye-mode state (thread-safe queues).
        self._eye_mode = False
        self._eye_mode_queue: queue.Queue[bool] = queue.Queue()
        self._mood_queue: queue.Queue[str] = queue.Queue()
        self._speaking_queue: queue.Queue[bool] = queue.Queue()
        self._eye_color_style = "bumblebee"  # "bumblebee" or "sentiment"
        self._color_style_queue: queue.Queue[str] = queue.Queue()
        self._ready_queue: queue.Queue[bool] = queue.Queue()

    # -- Public API ---------------------------------------------------------

    def switch_gif(self, gif_path: str) -> None:
        """Thread-safe GIF swap — picked up by render loop."""
        self._swap_queue.put(gif_path)

    def switch_to_eyes(self, color_style: str = "bumblebee") -> None:
        """Switch to eye-rendering mode. color_style: 'bumblebee' or 'sentiment'."""
        self._color_style_queue.put(color_style)
        self._eye_mode_queue.put(True)

    def switch_to_gif(self, gif_path: str) -> None:
        """Switch back to GIF mode."""
        self._eye_mode_queue.put(False)
        self._swap_queue.put(gif_path)

    def set_mood(self, mood: str) -> None:
        """Thread-safe mood change (eye mode only)."""
        self._mood_queue.put(mood)

    def set_speaking(self, speaking: bool) -> None:
        """Thread-safe speaking state (eye mode only)."""
        self._speaking_queue.put(speaking)

    def switch_to_ready(self) -> None:
        """Revert LCD to the startup ready text (e.g. on disconnect)."""
        self._eye_mode_queue.put(False)
        self._ready_queue.put(True)

    def start(self):
        if not self._mock:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("GifDisplay thread started (mock=%s)", self._mock)

    def run_blocking(self):
        self._running = True
        logger.info("GifDisplay running on main thread")
        self._run()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    # -- GIF loading --------------------------------------------------------

    def _load_gif_frames(self, gif_path: str) -> None:
        try:
            gif = Image.open(gif_path)
        except (FileNotFoundError, Exception) as e:
            logger.warning("GIF not found or invalid: %s (%s)", gif_path, e)
            placeholder = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
            placeholder.fill((40, 40, 40))
            font = pygame.font.SysFont(None, 36)
            name = os.path.basename(gif_path).replace(".gif", "")
            text = font.render(name.upper(), True, (255, 255, 255))
            rect = text.get_rect(center=(LCD_WIDTH // 2, LCD_HEIGHT // 2))
            placeholder.blit(text, rect)
            self._frames = [placeholder]
            self._frame_durations = [0.1]
            return

        frames, durations = [], []
        try:
            while True:
                frame_rgb = gif.convert("RGB").resize((LCD_WIDTH, LCD_HEIGHT))
                raw = frame_rgb.tobytes()
                surface = pygame.image.fromstring(raw, (LCD_WIDTH, LCD_HEIGHT), "RGB")
                frames.append(surface)
                duration_ms = gif.info.get("duration", 100)
                durations.append(max(duration_ms / 1000.0, 0.03))
                gif.seek(gif.tell() + 1)
        except EOFError:
            pass

        if not frames:
            placeholder = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))
            placeholder.fill((40, 40, 40))
            frames = [placeholder]
            durations = [0.1]

        self._frames = frames
        self._frame_durations = durations
        self._current_gif = gif_path
        logger.info("Loaded %d GIF frames from %s", len(frames), gif_path)

    # -- Eye drawing --------------------------------------------------------

    @staticmethod
    def _draw_eye(surface, cx, cy, scale, squash, colors, blink_t, now):
        ps = 1.0 + 0.02 * math.sin(2 * math.pi * now / 2.5)
        s = scale * ps
        glow_r = int(GLOW_RADIUS * s)
        outer_r = int(EYE_RADIUS * s)
        iris_r = int(IRIS_RADIUS * s)
        pupil_r = int(PUPIL_RADIUS * s)
        tick_in = int(TICK_INNER * s)
        tick_out = int(TICK_OUTER * s)
        vs = max(0.05, squash * (1.0 - blink_t))

        # Glow
        gs = pygame.Surface((glow_r*2+4, int((glow_r*2+4)*vs)+4), pygame.SRCALPHA)
        gcx, gcy = glow_r+2, int((glow_r+2)*vs)
        for i in range(4):
            r = glow_r - i*4
            if r < 1: break
            ry = max(1, int(r*vs))
            pygame.draw.ellipse(gs, (*colors["glow"], 25+i*10), (gcx-r, gcy-ry, r*2, ry*2))
        surface.blit(gs, (cx-gcx, cy-gcy))

        # Outer ring
        ryo = max(1, int(outer_r*vs))
        pygame.draw.ellipse(surface, colors["outer"], (cx-outer_r, cy-ryo, outer_r*2, ryo*2), 3)

        # Ticks
        for i in range(TICK_COUNT):
            a = (2*math.pi/TICK_COUNT)*i + now*0.3
            x1 = cx+int(tick_in*math.cos(a)); y1 = cy+int(tick_in*math.sin(a)*vs)
            x2 = cx+int(tick_out*math.cos(a)); y2 = cy+int(tick_out*math.sin(a)*vs)
            pygame.draw.line(surface, colors["tick"], (x1,y1), (x2,y2), TICK_WIDTH)

        # Iris
        ryi = max(1, int(iris_r*vs))
        pygame.draw.ellipse(surface, colors["iris"], (cx-iris_r, cy-ryi, iris_r*2, ryi*2))

        # Dark ring
        mr = (iris_r+pupil_r)//2; rym = max(1, int(mr*vs))
        pygame.draw.ellipse(surface, _lerp_color(colors["iris"], BLACK, 0.45), (cx-mr, cy-rym, mr*2, rym*2))

        # Pupil
        ryp = max(1, int(pupil_r*vs))
        pygame.draw.ellipse(surface, colors["pupil"], (cx-pupil_r, cy-ryp, pupil_r*2, ryp*2))

        # Highlight
        if vs > 0.3:
            hr = max(2, int(4*s))
            hx = cx+int(pupil_r*0.35); hy = cy-int(pupil_r*0.35*vs)
            pygame.draw.circle(surface, colors["highlight"], (hx, hy), hr)

    @staticmethod
    def _draw_visor(surface, colors, lcx, rcx, cy, squash, blink_t):
        vs = max(0.05, squash * (1.0 - blink_t))
        hh = max(1, int(VISOR_HEIGHT*0.5*vs))
        x1 = lcx - EYE_RADIUS - VISOR_EXTEND
        x2 = rcx + EYE_RADIUS + VISOR_EXTEND
        vs_surf = pygame.Surface((x2-x1, hh*2), pygame.SRCALPHA)
        vs_surf.fill((*colors["visor"], 160))
        surface.blit(vs_surf, (x1, cy-hh))
        pygame.draw.line(surface, colors["outer"], (x1, cy-hh), (x2, cy-hh), 1)
        pygame.draw.line(surface, colors["outer"], (x1, cy+hh), (x2, cy+hh), 1)

    @staticmethod
    def _draw_mouth(surface, colors, speaking, now):
        cx = LCD_WIDTH // 2
        seg_total_h = MOUTH_HEIGHT - (MOUTH_SEGMENTS-1)*MOUTH_SEG_GAP
        seg_h = max(2, seg_total_h // MOUTH_SEGMENTS)
        left = cx - MOUTH_WIDTH//2
        pygame.draw.rect(surface, colors["mouth_frame"],
                         (left-4, MOUTH_Y-MOUTH_HEIGHT//2-3, MOUTH_WIDTH+8, MOUTH_HEIGHT+6),
                         2, border_radius=MOUTH_CORNER_R)
        for i in range(MOUTH_SEGMENTS):
            y = MOUTH_Y - MOUTH_HEIGHT//2 + i*(seg_h+MOUTH_SEG_GAP)
            if speaking:
                phase = now*8.0 - i*0.7
                br = 0.4 + 0.6*max(0.0, math.sin(phase))
                color = _lerp_color(colors["mouth_seg"], colors["mouth_active"], br)
                wf = 0.85 + 0.15*br
            else:
                cd = abs(i - MOUTH_SEGMENTS//2) / max(1, MOUTH_SEGMENTS//2)
                br = 0.3 + 0.15*(1.0-cd)
                color = _lerp_color(BLACK, colors["mouth_seg"], br)
                wf = 0.8
            sw = int(MOUTH_WIDTH*wf)
            sl = cx - sw//2
            pygame.draw.rect(surface, color, (sl, y, sw, seg_h))

    # -- LCD ----------------------------------------------------------------

    def _create_lcd(self):
        bsp_path = "/usr/local/lib/python3.10/dist-packages"
        if bsp_path not in sys.path:
            sys.path.insert(0, bsp_path)
        try:
            from MangDang.LCD.ST7789 import ST7789
            lcd = ST7789()
            logger.info("ST7789 LCD initialized")
            return lcd
        except ImportError:
            logger.error("MangDang.LCD.ST7789 not found")
            return None

    def _surface_to_pil(self, surface: pygame.Surface) -> Image.Image:
        raw = pygame.image.tostring(surface, "RGB")
        return Image.frombytes("RGB", surface.get_size(), raw)

    # -- Main loop ----------------------------------------------------------

    def _run(self):
        pygame.init()

        if self._mock:
            screen = pygame.display.set_mode((LCD_WIDTH * MOCK_SCALE, LCD_HEIGHT * MOCK_SCALE))
            pygame.display.set_caption("pupper-talk")
        else:
            screen = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))

        lcd = None if self._mock else self._create_lcd()
        render_surface = pygame.Surface((LCD_WIDTH, LCD_HEIGHT))

        if self._current_gif:
            self._load_gif_frames(self._current_gif)
        else:
            render_surface.fill((0, 0, 0))
            font_size = 56 if len(self._ready_text) <= 12 else 40
            font = pygame.font.SysFont(None, font_size)
            text = font.render(self._ready_text, True, (255, 255, 255))
            rect = text.get_rect(center=(LCD_WIDTH // 2, LCD_HEIGHT // 2))
            render_surface.blit(text, rect)
            self._frames = [render_surface.copy()]
            self._frame_durations = [1.0]

        eye_mode = self._eye_mode
        frame_idx = 0
        clock = pygame.time.Clock()

        # Eye state
        current_mood = "neutral"
        speaking = False
        color_style = self._eye_color_style  # "bumblebee" or "sentiment"
        active_colors = dict(_BEE_YELLOW)
        active_shape = dict(_MOOD_SHAPE["neutral"])
        next_blink = time.monotonic() + random.uniform(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX)
        blink_start = None

        while self._running:
            now = time.monotonic()

            # Check eye mode toggle.
            try:
                while True:
                    eye_mode = self._eye_mode_queue.get_nowait()
                    self._eye_mode = eye_mode
                    if eye_mode:
                        logger.info("Display: switched to EYE mode")
                    else:
                        logger.info("Display: switched to GIF mode")
            except queue.Empty:
                pass

            # Check ready text request (forces back to startup text).
            try:
                self._ready_queue.get_nowait()
                render_surface.fill((0, 0, 0))
                font_size = 56 if len(self._ready_text) <= 12 else 40
                font = pygame.font.SysFont(None, font_size)
                text = font.render(self._ready_text, True, (255, 255, 255))
                rect = text.get_rect(center=(LCD_WIDTH // 2, LCD_HEIGHT // 2))
                render_surface.blit(text, rect)
                self._frames = [render_surface.copy()]
                self._frame_durations = [1.0]
                self._current_gif = None
                frame_idx = 0
                eye_mode = False
                self._eye_mode = False
                logger.info("Display: reverted to ready text")
            except queue.Empty:
                pass

            # Check GIF swap.
            if not eye_mode:
                try:
                    new_gif = self._swap_queue.get_nowait()
                    if new_gif != self._current_gif:
                        self._load_gif_frames(new_gif)
                        frame_idx = 0
                except queue.Empty:
                    pass
            else:
                # Drain swap queue in eye mode (discard).
                try:
                    while True:
                        self._swap_queue.get_nowait()
                except queue.Empty:
                    pass

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    return

            if eye_mode:
                # -- Eye rendering --
                dt = 1.0 / 30

                # Color style queue
                try:
                    while True:
                        color_style = self._color_style_queue.get_nowait()
                        self._eye_color_style = color_style
                except queue.Empty:
                    pass

                # Mood queue
                try:
                    while True:
                        m = self._mood_queue.get_nowait()
                        if m in _MOOD_SHAPE:
                            current_mood = m
                except queue.Empty:
                    pass

                # Speaking queue
                try:
                    while True:
                        speaking = self._speaking_queue.get_nowait()
                except queue.Empty:
                    pass

                # Smooth interpolation — target colors depend on style.
                if color_style == "sentiment":
                    target_colors = _SENTIMENT_COLORS.get(current_mood, _SENTIMENT_COLORS["neutral"])
                else:
                    target_colors = _BEE_YELLOW
                target_shape = _MOOD_SHAPE.get(current_mood, _MOOD_SHAPE["neutral"])
                ls = 4.0 * dt
                for key in active_colors:
                    active_colors[key] = _lerp_color(active_colors[key], target_colors[key], ls)
                for key in active_shape:
                    active_shape[key] += (target_shape[key] - active_shape[key]) * ls

                # Blink
                if blink_start is None and now >= next_blink:
                    blink_start = now
                blink_t = 0.0
                if blink_start is not None:
                    elapsed = now - blink_start
                    if elapsed < BLINK_DURATION:
                        half = BLINK_DURATION / 2
                        blink_t = elapsed/half if elapsed < half else (BLINK_DURATION-elapsed)/half
                        blink_t = max(0.0, min(1.0, blink_t))
                    else:
                        blink_start = None
                        next_blink = now + random.uniform(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX)

                cx = LCD_WIDTH // 2
                cy = EYE_CENTER_Y + int(active_shape["y_offset"])
                lcx = cx - EYE_SPACING // 2
                rcx = cx + EYE_SPACING // 2
                vs = active_shape["squash"]

                render_surface.fill(BLACK)
                self._draw_visor(render_surface, active_colors, lcx, rcx, cy, vs, blink_t)
                self._draw_eye(render_surface, lcx, cy,
                               active_shape["scale"]*active_shape["left_scale"], vs, active_colors, blink_t, now)
                self._draw_eye(render_surface, rcx, cy,
                               active_shape["scale"]*active_shape["right_scale"], vs, active_colors, blink_t, now)
                self._draw_mouth(render_surface, active_colors, speaking, now)

                if self._mock:
                    scaled = pygame.transform.scale(render_surface, (LCD_WIDTH*MOCK_SCALE, LCD_HEIGHT*MOCK_SCALE))
                    screen.blit(scaled, (0, 0))
                    pygame.display.flip()
                elif lcd is not None:
                    pil_image = self._surface_to_pil(render_surface)
                    lcd.display(pil_image)

                clock.tick(30)
            else:
                # -- GIF rendering --
                current_frame = self._frames[frame_idx]

                if self._mock:
                    scaled = pygame.transform.scale(current_frame, (LCD_WIDTH*MOCK_SCALE, LCD_HEIGHT*MOCK_SCALE))
                    screen.blit(scaled, (0, 0))
                    pygame.display.flip()
                else:
                    screen.blit(current_frame, (0, 0))
                    if lcd:
                        pil_image = self._surface_to_pil(screen)
                        lcd.display(pil_image)

                duration = self._frame_durations[frame_idx]
                frame_idx = (frame_idx + 1) % len(self._frames)
                pygame.time.wait(int(duration * 1000))

        pygame.quit()
