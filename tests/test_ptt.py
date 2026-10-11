"""`record_multi` with an inbox: an item from the page ends the wait without a microphone."""
import threading
import time

import pytest

from fish_brain import ptt
from fish_brain.config import PTTConfig


@pytest.fixture(autouse=True)
def no_microphone(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the microphone must not be opened")
    monkeypatch.setattr(ptt, "_record_until", boom)
    monkeypatch.setattr(ptt, "_cut_last", False)


class Item:
    pass


def test_inbox_item_returns_without_a_microphone():
    never_held = ptt.ButtonSource(lambda: False, name="web")
    item = Item()
    got = ptt.record_multi(PTTConfig(), [never_held], inbox=lambda: item)
    assert got is item


def test_inbox_item_wins_over_a_stale_press():
    # The button reads held from the start (a lost release): the wait for idle still listens.
    stuck = ptt.ButtonSource(lambda: True, name="web")
    item = Item()
    assert ptt.record_multi(PTTConfig(), [stuck], inbox=lambda: item) is item


def test_sources_are_disarmed_after_an_inbox_item():
    armed = []
    src = ptt.ButtonSource(lambda: False, arm=armed.append, name="remote")
    ptt.record_multi(PTTConfig(), [src], inbox=lambda: Item())
    assert armed == [True, False]


def test_no_sources_waits_on_the_inbox():
    box = []
    item = Item()
    threading.Timer(0.1, lambda: box.append(item)).start()
    t0 = time.monotonic()
    got = ptt.record_multi(PTTConfig(), [], inbox=lambda: box.pop() if box else None)
    assert got is item and 0.05 < time.monotonic() - t0 < 2.0


def test_no_sources_and_no_inbox_is_unavailable():
    with pytest.raises(ptt.PTTUnavailable):
        ptt.record_multi(PTTConfig(), [])
