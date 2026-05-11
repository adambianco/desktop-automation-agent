"""
Vision — UI element detection using OpenCV template matching and OCR.

Provides two complementary strategies:
  1. Template Matching: locate a known image (button, icon, logo) on screen.
  2. OCR Text Search: find text on screen using Tesseract via pytesseract.

Both strategies return bounding boxes and center coordinates for use by
the InputController.
"""

import os
import logging
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Optional pytesseract — gracefully degrade if not installed
try:
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False
    logger.warning("pytesseract not available; OCR features disabled")


@dataclass
class UIElement:
    """Represents a detected UI element on screen."""
    label: str                          # Human-readable name (e.g. "Save Button")
    x: int                              # Left edge (screen coordinates)
    y: int                              # Top edge (screen coordinates)
    width: int
    height: int
    confidence: float = 1.0            # Match confidence [0.0 – 1.0]
    method: str = "template"           # "template" | "ocr" | "manual"
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def center(self) -> Tuple[int, int]:
        """Return the center (x, y) of the element."""
        return self.x + self.width // 2, self.y + self.height // 2

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        """Return (x, y, width, height)."""
        return self.x, self.y, self.width, self.height

    def __repr__(self) -> str:
        cx, cy = self.center
        return (f"UIElement(label={self.label!r}, center=({cx},{cy}), "
                f"conf={self.confidence:.2f}, method={self.method!r})")


class Vision:
    """
    Detects UI elements on a screenshot using template matching and OCR.

    Usage:
        vision = Vision()
        screen = screen_capture.capture()

        # Find a button by template image
        el = vision.find_template(screen, "templates/save_btn.png", label="Save")

        # Find text on screen
        el = vision.find_text(screen, "Submit", label="Submit Button")
    """

    def __init__(self, template_dir: str = "templates",
                 default_threshold: float = 0.80):
        """
        Args:
            template_dir: Directory containing template images.
            default_threshold: Minimum confidence for a template match [0–1].
        """
        self.template_dir = template_dir
        self.default_threshold = default_threshold
        self._template_cache: Dict[str, np.ndarray] = {}
        logger.info("Vision initialized (template_dir=%s, threshold=%.2f)",
                    template_dir, default_threshold)

    # ------------------------------------------------------------------ #
    #  Template Matching                                                   #
    # ------------------------------------------------------------------ #

    def _load_template(self, template_path: str) -> np.ndarray:
        """Load and cache a template image as a grayscale NumPy array."""
        if template_path not in self._template_cache:
            # Resolve relative paths against template_dir
            if not os.path.isabs(template_path):
                template_path = os.path.join(self.template_dir, template_path)
            if not os.path.exists(template_path):
                raise FileNotFoundError(f"Template not found: {template_path}")
            tmpl = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if tmpl is None:
                raise ValueError(f"Could not read template image: {template_path}")
            self._template_cache[template_path] = tmpl
            logger.debug("Template loaded: %s (%dx%d)", template_path,
                         tmpl.shape[1], tmpl.shape[0])
        return self._template_cache[template_path]

    def find_template(self, screen: np.ndarray, template_path: str,
                      label: str = "", threshold: float = None,
                      region: Optional[Tuple[int, int, int, int]] = None
                      ) -> Optional[UIElement]:
        """
        Find the best match of a template image on the screen.

        Args:
            screen: BGR screenshot as NumPy array.
            template_path: Path to the template image file.
            label: Human-readable name for the element.
            threshold: Override the default confidence threshold.
            region: Optional (x, y, w, h) to restrict the search area.

        Returns:
            UIElement if found above threshold, else None.
        """
        thresh = threshold if threshold is not None else self.default_threshold
        tmpl = self._load_template(template_path)
        th, tw = tmpl.shape[:2]

        # Convert screen to grayscale for matching
        if len(screen.shape) == 3:
            gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        else:
            gray_screen = screen

        # Restrict to region if specified
        offset_x, offset_y = 0, 0
        if region:
            rx, ry, rw, rh = region
            gray_screen = gray_screen[ry:ry + rh, rx:rx + rw]
            offset_x, offset_y = rx, ry

        result = cv2.matchTemplate(gray_screen, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= thresh:
            x = max_loc[0] + offset_x
            y = max_loc[1] + offset_y
            el = UIElement(
                label=label or os.path.basename(template_path),
                x=x, y=y, width=tw, height=th,
                confidence=float(max_val),
                method="template"
            )
            logger.debug("Template match found: %s (conf=%.3f)", el.label, el.confidence)
            return el

        logger.debug("Template match below threshold: %s (best=%.3f < %.3f)",
                     template_path, max_val, thresh)
        return None

    def find_all_templates(self, screen: np.ndarray, template_path: str,
                           label: str = "", threshold: float = None
                           ) -> List[UIElement]:
        """
        Find ALL occurrences of a template on screen (e.g., multiple buttons).

        Returns:
            List of UIElement instances, sorted by confidence descending.
        """
        thresh = threshold if threshold is not None else self.default_threshold
        tmpl = self._load_template(template_path)
        th, tw = tmpl.shape[:2]

        if len(screen.shape) == 3:
            gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        else:
            gray_screen = screen

        result = cv2.matchTemplate(gray_screen, tmpl, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= thresh)
        elements = []

        for pt in zip(*locations[::-1]):  # (x, y) pairs
            conf = float(result[pt[1], pt[0]])
            elements.append(UIElement(
                label=label or os.path.basename(template_path),
                x=int(pt[0]), y=int(pt[1]),
                width=tw, height=th,
                confidence=conf,
                method="template"
            ))

        # Non-maximum suppression to remove overlapping detections
        elements = self._nms(elements, overlap_threshold=0.5)
        elements.sort(key=lambda e: e.confidence, reverse=True)
        logger.debug("Found %d template matches for %s", len(elements), template_path)
        return elements

    @staticmethod
    def _nms(elements: List[UIElement], overlap_threshold: float = 0.5
             ) -> List[UIElement]:
        """Simple non-maximum suppression to remove duplicate detections."""
        if not elements:
            return []

        boxes = np.array([[e.x, e.y, e.x + e.width, e.y + e.height]
                          for e in elements], dtype=float)
        scores = np.array([e.confidence for e in elements])
        indices = list(range(len(elements)))
        indices.sort(key=lambda i: scores[i], reverse=True)

        kept = []
        while indices:
            best = indices.pop(0)
            kept.append(best)
            x1, y1, x2, y2 = boxes[best]
            area_best = (x2 - x1) * (y2 - y1)

            remaining = []
            for idx in indices:
                ix1 = max(x1, boxes[idx][0])
                iy1 = max(y1, boxes[idx][1])
                ix2 = min(x2, boxes[idx][2])
                iy2 = min(y2, boxes[idx][3])
                iw = max(0, ix2 - ix1)
                ih = max(0, iy2 - iy1)
                intersection = iw * ih
                area_idx = ((boxes[idx][2] - boxes[idx][0]) *
                            (boxes[idx][3] - boxes[idx][1]))
                union = area_best + area_idx - intersection
                if union > 0 and intersection / union < overlap_threshold:
                    remaining.append(idx)
            indices = remaining

        return [elements[i] for i in kept]

    # ------------------------------------------------------------------ #
    #  OCR Text Detection                                                  #
    # ------------------------------------------------------------------ #

    def find_text(self, screen: np.ndarray, text: str, label: str = "",
                  case_sensitive: bool = False,
                  region: Optional[Tuple[int, int, int, int]] = None
                  ) -> Optional[UIElement]:
        """
        Find the first occurrence of a text string on screen using OCR.

        Args:
            screen: BGR screenshot as NumPy array.
            text: The text string to search for.
            label: Human-readable label for the element.
            case_sensitive: Whether the search is case-sensitive.
            region: Optional (x, y, w, h) to restrict the search area.

        Returns:
            UIElement if found, else None.
        """
        if not _OCR_AVAILABLE:
            logger.error("OCR unavailable: pytesseract not installed")
            return None

        offset_x, offset_y = 0, 0
        search_screen = screen
        if region:
            rx, ry, rw, rh = region
            search_screen = screen[ry:ry + rh, rx:rx + rw]
            offset_x, offset_y = rx, ry

        pil_img = Image.fromarray(search_screen[:, :, ::-1])  # BGR → RGB
        data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)

        search_text = text if case_sensitive else text.lower()
        n = len(data["text"])

        for i in range(n):
            word = data["text"][i]
            if not word.strip():
                continue
            candidate = word if case_sensitive else word.lower()
            if search_text in candidate:
                x = data["left"][i] + offset_x
                y = data["top"][i] + offset_y
                w = data["width"][i]
                h = data["height"][i]
                conf = float(data["conf"][i]) / 100.0
                el = UIElement(
                    label=label or text,
                    x=x, y=y, width=max(w, 1), height=max(h, 1),
                    confidence=conf,
                    method="ocr"
                )
                logger.debug("OCR text found: %r → %s", text, el)
                return el

        logger.debug("OCR text not found: %r", text)
        return None

    def find_all_text(self, screen: np.ndarray, text: str,
                      case_sensitive: bool = False) -> List[UIElement]:
        """Find all occurrences of a text string on screen via OCR."""
        if not _OCR_AVAILABLE:
            return []

        pil_img = Image.fromarray(screen[:, :, ::-1])
        data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)
        search_text = text if case_sensitive else text.lower()
        results = []

        for i in range(len(data["text"])):
            word = data["text"][i]
            if not word.strip():
                continue
            candidate = word if case_sensitive else word.lower()
            if search_text in candidate:
                conf = float(data["conf"][i]) / 100.0
                results.append(UIElement(
                    label=text,
                    x=data["left"][i], y=data["top"][i],
                    width=max(data["width"][i], 1),
                    height=max(data["height"][i], 1),
                    confidence=conf,
                    method="ocr"
                ))

        logger.debug("OCR found %d occurrences of %r", len(results), text)
        return results

    def extract_all_text(self, screen: np.ndarray,
                         region: Optional[Tuple[int, int, int, int]] = None
                         ) -> str:
        """Extract all visible text from the screen (or a region) via OCR."""
        if not _OCR_AVAILABLE:
            return ""

        search_screen = screen
        if region:
            rx, ry, rw, rh = region
            search_screen = screen[ry:ry + rh, rx:rx + rw]

        pil_img = Image.fromarray(search_screen[:, :, ::-1])
        text = pytesseract.image_to_string(pil_img)
        logger.debug("OCR extracted %d chars", len(text))
        return text

    # ------------------------------------------------------------------ #
    #  Pixel / Color Detection                                             #
    # ------------------------------------------------------------------ #

    def get_pixel_color(self, screen: np.ndarray, x: int, y: int
                        ) -> Tuple[int, int, int]:
        """Return the (R, G, B) color of a pixel at (x, y)."""
        bgr = screen[y, x]
        return int(bgr[2]), int(bgr[1]), int(bgr[0])

    def pixel_matches_color(self, screen: np.ndarray, x: int, y: int,
                            expected_rgb: Tuple[int, int, int],
                            tolerance: int = 10) -> bool:
        """
        Check if a pixel matches an expected color within a tolerance.

        Args:
            tolerance: Maximum allowed difference per channel.
        """
        r, g, b = self.get_pixel_color(screen, x, y)
        er, eg, eb = expected_rgb
        return (abs(r - er) <= tolerance and
                abs(g - eg) <= tolerance and
                abs(b - eb) <= tolerance)

    # ------------------------------------------------------------------ #
    #  Debug Utilities                                                     #
    # ------------------------------------------------------------------ #

    def annotate_screenshot(self, screen: np.ndarray,
                            elements: List[UIElement],
                            output_path: str) -> None:
        """
        Draw bounding boxes and labels on a screenshot for debugging.
        Saves the annotated image to output_path.
        """
        annotated = screen.copy()
        for el in elements:
            cv2.rectangle(annotated,
                          (el.x, el.y),
                          (el.x + el.width, el.y + el.height),
                          (0, 255, 0), 2)
            cv2.putText(annotated, f"{el.label} ({el.confidence:.2f})",
                        (el.x, el.y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imwrite(output_path, annotated)
        logger.info("Annotated screenshot saved: %s", output_path)
