"""Pill identity by Claude vision: each pill on the tray is compared with enrolled reference photos. No training.

  python identify_claude.py check frame.jpg      needs ANTHROPIC_API_KEY (a line in .env is enough)
  python app.py --claude                         the station checks every pill this way before placing it

Two independent checks must agree before a pill is named: Claude, shown reference crops of every enrolled pill type,
and identify.py's measured colour, size and roundness. If either says unknown, or they disagree, the answer is
unknown and the station refuses the pill. A confident wrong name is the failure that matters for medication.
Scenery (the organizer, the jaws, tape) is gated out by identify.py first and never sent to the API.
"""
import base64
import json
import sys
from pathlib import Path

import cv2

import identify

MODEL = "claude-opus-5-5"
REFS_PER_LABEL = 2
SYSTEM = ("You check pills for a robot that fills a weekly pill organizer for a person with low vision. A wrong name "
          "could put the wrong medicine into their week, so answer unknown whenever the candidate differs from the "
          "references in any way, or whenever you are not sure. Lighting and camera angle vary; shape, colour, "
          "size and markings do not.")


def image_block(img) -> dict:
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise ValueError("could not encode crop")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.tobytes()).decode()}}


class ClaudeIdentifier:
    def __init__(self, root: Path = identify.DATA, client=None, agree: bool = True):
        self.gallery = identify.Gallery(identify.Features(), root=root)  # scenery gates + the second opinion
        self.labels = sorted(set(self.gallery.labels))
        self.refs = self._refs(root)
        if client is None:
            import anthropic
            client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from the environment; config.py loads .env
        self.client, self.agree = client, agree

    def _refs(self, root: Path) -> dict:
        refs = {}
        for label in self.labels:
            picked = []
            for f in sorted([*(root / label).glob("*.png"), *(root / label).glob("*.jpg")]):
                img = cv2.imread(str(f))
                found = identify.crops(img) if img is not None else []
                if found:
                    picked.append(identify.enrol_pick(found, img.shape)[1])
                if len(picked) == REFS_PER_LABEL:
                    break
            refs[label] = picked
        return refs

    def ask(self, crop) -> dict:
        content = []
        for label in self.labels:
            content.append({"type": "text", "text": f"Reference photos of {label}:"})
            content += [image_block(c) for c in self.refs[label]]
        content += [{"type": "text", "text": "Candidate pill:"}, image_block(crop),
                    {"type": "text", "text": "Which enrolled pill is the candidate? Name one only if its shape, colour, "
                                             "size and markings all match that pill's references; otherwise unknown."}]
        schema = {"type": "object", "additionalProperties": False, "required": ["label", "reason"],
                  "properties": {"label": {"type": "string", "enum": [*self.labels, "unknown"]},
                                 "reason": {"type": "string"}}}
        resp = self.client.beta.messages.create(
            model=MODEL, max_tokens=2048, system=SYSTEM,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
        if resp.stop_reason == "refusal":
            return {"label": "unknown", "reason": "the model declined"}
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            return {"label": "unknown", "reason": f"no answer ({resp.stop_reason})"}
        out = json.loads(text)
        if out.get("label") not in self.labels:
            out["label"] = "unknown"
        return out

    def identify(self, img) -> list[dict]:
        out = []
        for r, (_pill, crop) in zip(self.gallery.identify(img), identify.crops(img)):
            if r["label"] == "not_pill":
                out.append(r)
                continue
            c = self.ask(crop)
            agreed = c["label"] == r["label"]
            label = c["label"] if agreed or not self.agree else "unknown"
            out.append({**r, "label": label, "claude": c["label"], "claude_reason": c.get("reason", ""),
                        "features": r["label"]})
        return out


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        sys.exit(__doc__)
    import config  # noqa: F401  loads ANTHROPIC_API_KEY from .env
    print(json.dumps(ClaudeIdentifier().identify(cv2.imread(sys.argv[2])), indent=1))
