import math
import re
import unicodedata


def normalize(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )


def local_goal(text: str, pose: dict, grid: dict) -> tuple[float, float]:
    """Translate bounded directional intents into an observed, clear straight corridor."""
    text = normalize(text)
    # Translate a deliberately narrow English grammar into the existing bounded
    # intent parser. Negations, compound commands, and unknown words still fail.
    english = re.fullmatch(
        r"(?:go|walk|move)(?:\s+(?:to|the|far|end|forward|backward|backwards|back|left|right|meters?|metres?|m|one|two|three|four|five|half|a|\d+(?:[.,]\d+)?))+(?:[.!?])?",
        text.strip(),
    )
    if english:
        text = re.sub(r"\bfar end\b", "fondo", text)
        words_en = {
            "go": "anda",
            "walk": "camina",
            "move": "mover",
            "to": "a",
            "the": "el",
            "forward": "adelante",
            "backward": "atras",
            "backwards": "atras",
            "back": "atras",
            "left": "izquierda",
            "right": "derecha",
            "meter": "metro",
            "meters": "metros",
            "metre": "metro",
            "metres": "metros",
            "one": "1",
            "two": "2",
            "three": "3",
            "four": "4",
            "five": "5",
            "half": "0.5",
        }
        text = re.sub(r"\b[a-z]+\b", lambda m: words_en.get(m[0], m[0]), text)
    # Spoken distances are as common as digits in the human interface.
    words = {
        "un": "1",
        "uno": "1",
        "una": "1",
        "dos": "2",
        "tres": "3",
        "cuatro": "4",
        "cinco": "5",
        "medio": "0.5",
    }
    text = re.sub(r"\b(un|uno|una|dos|tres|cuatro|cinco|medio)\b", lambda m: words[m[0]], text)
    if len(text) > 200 or re.search(r"\b(no|evita|evitar|pero|despues|luego)\b", text):
        raise ValueError(
            "Use a single instruction: “walk 2 meters”, “go to the far end”, or “move left”."
        )
    patterns = [
        (
            r"(?:anda|ve|avanza|avanza|camina|mover|move|muevete)(?:\s+(?:hacia|hasta|al|a|el|la|los|las|unos|unas|de|metros?|m|fondo|adelante|frente|atras|izquierda|derecha|\d+(?:[.,]\d+)?))+$",
            None,
        )
    ]
    if not any(re.fullmatch(pattern, text.strip(" .!?")) for pattern, _ in patterns):
        raise ValueError(
            "Local HumanCLI recognizes directions and distances. Try “walk 2 meters” or “go to the far end”."
        )
    directions = [word for word in ("izquierda", "derecha", "atras") if word in text]
    if len(directions) > 1:
        raise ValueError("Specify one direction")
    angle = pose["yaw"] + (
        {"izquierda": math.pi / 2, "derecha": -math.pi / 2, "atras": math.pi}.get(directions[0], 0)
        if directions
        else 0
    )
    number = re.search(r"\d+(?:[.,]\d+)?", text)
    distance = (
        float(number.group().replace(",", ".")) if number else (5.0 if "fondo" in text else 1.0)
    )
    if not 0.2 <= distance <= 5:
        raise ValueError("Distance must be between 0.2 and 5 meters")
    last = None
    step = max(0.05, min(grid["resolution"], 0.1))
    for n in range(1, math.ceil(distance / step) + 1):
        d = min(distance, n * step)
        x, y = pose["x"] + math.cos(angle) * d, pose["y"] + math.sin(angle) * d
        # Keep a 30cm radius within known free cells. The DimOS planner also checks its footprint.
        clearance = max(1, math.ceil(0.3 / grid["resolution"]))
        col = math.floor((x - grid["origin"][0]) / grid["resolution"])
        row = math.floor((y - grid["origin"][1]) / grid["resolution"])
        valid = True
        for dy in range(-clearance, clearance + 1):
            for dx in range(-clearance, clearance + 1):
                cx, cy = col + dx, row + dy
                if (
                    not (0 <= cx < grid["width"] and 0 <= cy < grid["height"])
                    or grid["cells"][cy * grid["width"] + cx] != 0
                ):
                    valid = False
                    break
            if not valid:
                break
        if not valid:
            break
        if d >= 0.3:
            last = (x, y)
    if last is None:
        raise ValueError(
            "There is no known clear corridor in that direction. Map more of the space using Teleop."
        )
    if number and math.hypot(last[0] - pose["x"], last[1] - pose["y"]) < distance - step:
        raise ValueError("The requested distance extends beyond the known clear corridor")
    return last
