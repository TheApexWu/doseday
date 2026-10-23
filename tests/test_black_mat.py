"""All-black construction-paper mat: white and coloured pills, uneven lamp light."""
import numpy as np

import vision
from synth import ellipse, mat

COLOURS = {"white": (235, 235, 235), "yellow": (40, 220, 240), "pink": (180, 140, 250),
           "orange": (30, 140, 250), "red": (30, 30, 200), "blue": (200, 60, 20), "green": (60, 160, 40)}


def _scene(light_gradient=0):
    img = mat(kind="black", noise=3, seed=1).astype(np.int16)
    if light_gradient:  # a lamp off to one side: the paper brightens left to right
        img += np.linspace(0, light_gradient, img.shape[1]).astype(np.int16)[None, :, None]
    img = np.clip(img, 0, 255).astype(np.uint8)
    pos = {}
    for i, (name, c) in enumerate(COLOURS.items()):
        x, y = 70 + (i % 4) * 150, 130 + (i // 4) * 200
        ellipse(img, x, y, 60, 24, 30, c)
        pos[name] = (x, y)
    return img, pos


def _found(img, pos):
    pills = vision.detect(img)
    hits = {n for n, (x, y) in pos.items() if any(abs(p.cx - x) < 10 and abs(p.cy - y) < 10 for p in pills)}
    return hits, len(pills)


def test_white_and_saturated_colours_show_on_black():
    hits, n = _found(*_scene())
    assert hits == set(COLOURS) and n == len(COLOURS)   # blue is ~60 in grey: needs the max-channel test


def test_uneven_lamp_light_does_not_create_false_pills():
    """A desk lamp hot spot: paper climbs from ~15 to ~140 across the frame. One global threshold
    either swallows the dim pills or calls the bright paper a pill; a local background does neither."""
    hits, n = _found(*_scene(light_gradient=125))
    assert hits == set(COLOURS) and n == len(COLOURS)


def test_near_black_pill_is_not_claimed():
    """Negative control: a pill as dark as the paper is invisible; stand-ins must be bright."""
    img = mat(kind="black", noise=3, seed=2)
    ellipse(img, 300, 240, 60, 24, 0, (35, 30, 30))
    assert vision.detect(img) == []


def test_bright_things_off_the_mat_are_not_pick_targets():
    """The rainbow organizer sits beside the mat in the camera view; only the tag quad is pickable."""
    from calib import outside_mat
    img = mat(kind="black", noise=3, seed=2)
    tags = {0: (100, 100), 1: (500, 100), 2: (500, 380), 3: (100, 380)}
    ellipse(img, 300, 240, 60, 24, 30, (235, 235, 235))   # pill on the mat
    ellipse(img, 580, 240, 50, 40, 0, (40, 220, 240))     # organizer lid off the mat
    everything = vision.detect(img)
    assert len(everything) == 2                           # control: without the mask both are seen
    on_mat = vision.detect(img, ignore=outside_mat(img.shape, tags))
    assert [(round(p.cx), round(p.cy)) for p in on_mat] == [(300, 240)]


def test_no_mat_filter_without_all_four_corner_tags():
    from calib import outside_mat
    assert outside_mat((480, 640), {0: (1, 1), 1: (9, 1), 2: (9, 9)}) is None


def test_live_detector_ignores_organizer_beside_tagged_mat():
    """End to end through demo.detect_masked: real ArUco tags on black paper, organizer off the mat."""
    import cv2
    import demo
    from calib import DEFAULT_LAYOUT, DICT
    ppm, margin = 2.0, 40.0
    w, h = int((300 + 2 * margin) * ppm), int((200 + 2 * margin) * ppm)
    img = np.full((h, w, 3), 20, np.uint8)
    d = cv2.aruco.getPredefinedDictionary(DICT)
    for i, (mx, my) in DEFAULT_LAYOUT.items():
        tag = cv2.copyMakeBorder(cv2.aruco.generateImageMarker(d, i, 60), 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
        cx, cy = int((mx + margin) * ppm), int((my + margin) * ppm)
        img[cy - 38:cy + 38, cx - 38:cx + 38] = tag[:, :, None]
    ellipse(img, w // 2, h // 2, 40, 16, 20, (235, 235, 235))      # pill mid-mat
    ellipse(img, w - 30, h // 2, 24, 40, 0, (40, 220, 240))        # organizer lid past tag 1/2
    found = [(round(p.cx), round(p.cy)) for p in demo.detect_masked(img, 50.0)]
    assert len(found) == 1 and abs(found[0][0] - w // 2) < 5
