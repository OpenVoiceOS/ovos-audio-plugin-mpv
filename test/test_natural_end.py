"""Regression test: a track that ends naturally (mpv's end-file event fires
with reason "eof", no stop() ever called) must report
PlaybackEvent.END_OF_MEDIA - the plugin reports the physical event, it
never emits bus state itself.

Also covers the bool contract on stop(): it must return True/False.
"""
import unittest
from unittest.mock import MagicMock

from ovos_utils.fakebus import FakeBus
from ovos_plugin_manager.templates.media import PlaybackEvent

from ovos_plugin_mpv import MPVOCPAudioService


class TestNaturalEndOfMedia(unittest.TestCase):

    def _service(self):
        bus = FakeBus()
        events = []
        service = MPVOCPAudioService({}, bus=bus)
        service.bind_event_reporter(lambda event, **data: events.append((event, data)))
        service.mpv = MagicMock()
        service._loaded_uri = "file:///tmp/track.wav"
        service._started.set()
        return service, events

    def test_natural_track_end_reports_end_of_media(self):
        service, events = self._service()

        # mpv's end-file event fires with reason "eof" when the track
        # finishes playing on its own, with no stop() ever called by us
        service._handle_end_file({"reason": "eof"})

        self.assertIn((PlaybackEvent.END_OF_MEDIA, {"uri": "file:///tmp/track.wav"}),
                       events,
                       f"natural end-of-media never reported END_OF_MEDIA; saw: {events}")

    def test_stop_returns_bool(self):
        service, _ = self._service()
        self.assertIs(service.stop(), True)
        self.assertIs(service.stop(), False)


if __name__ == "__main__":
    unittest.main()
