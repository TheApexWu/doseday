"""identify_claude.py with a scripted fake client: no network. Names a pill only when Claude and the features agree."""
import json
from types import SimpleNamespace

import cv2
import pytest

import identify_claude
from tests.synth import BLUE_C, OVAL_C, ROUND_C, capsule, ellipse, frames, mat


class FakeMessages:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def create(self, **kw):
        self.calls.append(kw)
        a = self.answers.pop(0)
        if a == "REFUSE":
            return SimpleNamespace(stop_reason="refusal", content=[])
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(a))])


def client(answers):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(answers)))


@pytest.fixture
def root(tmp_path):
    d = tmp_path / "data"
    for label, imgs in {"tums": frames(ROUND_C, 40, 40, n=4, seed=1), "magnesium": frames(OVAL_C, 60, 26, n=4, seed=2)}.items():
        (d / label).mkdir(parents=True)
        for i, img in enumerate(imgs):
            cv2.imwrite(str(d / label / f"{i}.png"), img)
    return d


def one(color, w, h):
    img = mat(noise=3, seed=8)
    ellipse(img, 320, 240, w, h, 30, color)
    return img


def test_agreement_names_the_pill_and_the_request_is_well_formed(root):
    c = client([{"label": "tums", "reason": "round orange, matches"}])
    got = identify_claude.ClaudeIdentifier(root, client=c).identify(one(ROUND_C, 40, 40))
    assert [r["label"] for r in got] == ["tums"]
    kw = c.beta.messages.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    images = [b for b in kw["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 2 * identify_claude.REFS_PER_LABEL + 1  # references for both labels + the candidate
    assert kw["output_config"]["format"]["schema"]["properties"]["label"]["enum"] == ["magnesium", "tums", "unknown"]


def test_disagreement_is_unknown_unless_agreement_is_switched_off(root):
    img = one(ROUND_C, 40, 40)  # the features engine says tums
    assert identify_claude.ClaudeIdentifier(root, client=client([{"label": "magnesium", "reason": "x"}])).identify(img)[0]["label"] == "unknown"
    assert identify_claude.ClaudeIdentifier(root, client=client([{"label": "magnesium", "reason": "x"}]), agree=False).identify(img)[0]["label"] == "magnesium"


def test_claude_unknown_wins_even_when_the_features_match(root):
    got = identify_claude.ClaudeIdentifier(root, client=client([{"label": "unknown", "reason": "imprint differs"}])).identify(one(OVAL_C, 60, 26))
    assert got[0]["label"] == "unknown" and got[0]["features"] == "magnesium"


def test_refusal_or_empty_answer_is_unknown(root):
    ident = identify_claude.ClaudeIdentifier(root, client=client(["REFUSE"]))
    got = ident.identify(one(ROUND_C, 40, 40))[0]
    assert got["label"] == "unknown" and "declined" in got["claude_reason"]


def test_scenery_never_reaches_the_api(root):
    img = mat(noise=3, seed=9)
    cv2.rectangle(img, (20, 200), (620, 300), (200, 200, 200), -1)  # organizer-sized blob
    c = client([])
    got = identify_claude.ClaudeIdentifier(root, client=c).identify(img)
    assert [r["label"] for r in got] == ["not_pill"] and c.beta.messages.calls == []
