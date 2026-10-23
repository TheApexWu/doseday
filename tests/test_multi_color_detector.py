import cv2
import numpy as np

from multi_color_detector import detect_colors


def test_detects_all_colors_at_once():
    image = np.full((300, 500, 3), 255, np.uint8)
    colors = {
        "red": (0, 0, 255),
        "black": (0, 0, 0),
        "orange": (0, 128, 255),
        "green": (0, 255, 0),
        "blue": (255, 0, 0),
        "cyan": (255, 255, 0),
        "purple": (255, 0, 128),
    }
    for i, color in enumerate(colors.values()):
        x = 20 + (i % 4) * 115
        y = 20 + (i // 4) * 130
        cv2.rectangle(image, (x, y), (x + 60, y + 60), color, -1)

    boxes = detect_colors(image)

    assert {box.label for box in boxes} == set(colors)


def test_suppresses_a_black_background_box():
    image = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(image, (100, 70), (160, 130), (0, 0, 255), -1)

    boxes = detect_colors(image)

    assert [box.label for box in boxes] == ["red"]
