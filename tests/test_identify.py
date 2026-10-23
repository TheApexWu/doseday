"""identify.py with the features engine on synthetic mats: names enrolled pills, refuses everything else."""
import threading

import cv2
import numpy as np
import pytest

import identify
from tests.synth import BLUE_C, OVAL_C, ROUND_C, capsule, ellipse, frames, mat


@pytest.fixture
def gallery_dir(tmp_path):
    root = tmp_path / "data"
    for label, imgs in {"tums": frames(ROUND_C, 40, 40, n=8, seed=1),
                        "magnesium": frames(OVAL_C, 60, 26, n=8, seed=2)}.items():
        (root / label).mkdir(parents=True)
        for i, img in enumerate(imgs):
            cv2.imwrite(str(root / label / f"{i}.png"), img)
    (root / "scene").mkdir()  # capture.py's scene folder is not a pill type
    cv2.imwrite(str(root / "scene" / "0.png"), frames(BLUE_C, 80, 24, n=1, seed=3)[0])
    return root


def table():
    img = mat(noise=3, seed=9)
    ellipse(img, 150, 150, 40, 40, 0, ROUND_C)       # a Tums
    ellipse(img, 450, 150, 60, 26, 70, OVAL_C)      # a magnesium tablet
    capsule(img, 300, 360, 80, 24, 20, BLUE_C)      # never enrolled
    return img


def by_position(results):
    return {(round(r["cx"] / 50) * 50, round(r["cy"] / 50) * 50): r for r in results}


def test_names_enrolled_and_refuses_the_rest(gallery_dir):
    g = identify.Gallery(identify.Features(), root=gallery_dir)
    assert sorted(set(g.labels)) == ["magnesium", "tums"]  # scene/ skipped
    got = {r["label"] for r in g.identify(table())}
    assert got == {"tums", "magnesium", "unknown"}


def test_unknown_reports_its_nearest_and_distance(gallery_dir):
    g = identify.Gallery(identify.Features(), root=gallery_dir)
    unk = [r for r in g.identify(table()) if r["label"] == "unknown"]
    assert len(unk) == 1 and unk[0]["dist"] > unk[0]["limit"] and unk[0]["nearest"] in {"tums", "magnesium"}


def test_white_round_of_the_wrong_size_is_not_a_tums_or_magnesium(gallery_dir):
    img = mat(noise=3, seed=4)
    ellipse(img, 320, 240, 90, 90, 0, OVAL_C)  # magnesium's colour, wrong shape and size
    g = identify.Gallery(identify.Features(), root=gallery_dir)
    assert [r["label"] for r in g.identify(img)] == ["unknown"]


def test_enrolment_takes_the_centre_pill_not_the_biggest_blob(tmp_path):
    root = tmp_path / "data" / "tums"
    root.mkdir(parents=True)
    for i, img in enumerate(frames(ROUND_C, 40, 40, n=4, seed=5)):
        cv2.rectangle(img, (0, 0), (120, 60), (230, 230, 230), -1)  # tape strip in the corner, far bigger
        cv2.imwrite(str(root / f"{i}.png"), img)
    g = identify.Gallery(identify.Features(), root=tmp_path / "data")
    assert np.exp(g.vecs[:, 3]).max() < 2500  # log area column: pill ~1250 px, tape would be ~7000


def test_empty_gallery_refuses_to_start(tmp_path):
    (tmp_path / "data").mkdir()
    with pytest.raises(SystemExit, match="needs photos"):
        identify.Gallery(identify.Features(), root=tmp_path / "data")


def test_server_round_trip_and_bad_body(gallery_dir):
    import requests
    g = identify.Gallery(identify.Features(), root=gallery_dir)
    srv = identify.make_server(g, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert {r["label"] for r in identify.client(url, table())} == {"tums", "magnesium", "unknown"}
        assert requests.get(url, timeout=5).json()["labels"] == ["magnesium", "tums"]
        assert requests.post(url, data=b"not an image", timeout=5).status_code == 400
    finally:
        srv.shutdown()


def test_size_wobble_within_camera_noise_still_names_the_pill(gallery_dir):
    # both enrolled types have ~1250 px area, so area barely varies across the gallery; without a noise
    # floor its scale collapses and a 7% size wobble (distance, lighting) reads as a different pill
    img = mat(noise=3, seed=6)
    ellipse(img, 320, 240, 62, 27, 40, OVAL_C)
    g = identify.Gallery(identify.Features(), root=gallery_dir, limit=0.9)
    assert [r["label"] for r in g.identify(img)] == ["magnesium"]
