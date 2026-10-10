"""验证协作声明的两平台共同决策与正文边界。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collaboration_notice import CHINESE, ENGLISH, decide, render


@pytest.mark.parametrize(
    "maintainer,assigned,include",
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (None, False, True),
        (None, True, False),
    ],
)
def test_auto(maintainer, assigned, include):
    assert decide("auto", maintainer, assigned)[0] is include


def test_removes_only_recognized_final_notice():
    assert render("Technical\n\n" + ENGLISH, False, CHINESE) == "Technical\n"
    assert render("Technical\n\n" + CHINESE, True, ENGLISH).count(ENGLISH) == 1
    unrelated = "Technical\n\n---\n\nUser-authored footer"
    assert render(unrelated, False, ENGLISH).strip() == unrelated
    embedded = ENGLISH + "\n\nTechnical"
    assert render(embedded, False, ENGLISH).strip() == embedded


def test_overrides():
    assert decide("always", True, True)[0]
    assert not decide("never", None, False)[0]
