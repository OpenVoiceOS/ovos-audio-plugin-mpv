"""Regression test: a track that ends naturally (mpv reports eof-reached on
its own, no stop() ever called) must report MediaState.END_OF_MEDIA /
PlayerState.STOPPED on the bus, exactly like an explicit stop does.

Also covers the bool contract on stop(): it must return True/False instead
of None.
"""
import unittest
from unittest.mock import MagicMock

from ovos_utils.fakebus import FakeBus
from ovos_utils.ocp import MediaState, PlayerState

from ovos_plugin_mpv import MPVOCPAudioService


class TestNaturalEndOfMedia(unittest.TestCase):

    def _service(self):
        bus = FakeBus()
        states = []
        player_states = []
        bus.on("ovos.common_play.media.state",
               lambda msg: states.append(msg.data.get("state")))
        bus.on("ovos.common_play.player.state",
               lambda msg: player_states.append(msg.data.get("state")))
        service = MPVOCPAudioService({}, bus=bus)
        service.mpv = MagicMock()
        service._now_playing = "file:///tmp/track.wav"
        service._started.set()
        return service, states, player_states

    def test_natural_track_end_emits_end_of_media(self):
        service, states, player_states = self._service()

        # simulate mpv's eof-reached property observer firing True after
        # playback started, with no stop() ever called by us
        service.handle_track_eof_status("eof-reached", True)

        self.assertIn(MediaState.END_OF_MEDIA, states,
                       f"natural end-of-media never emitted END_OF_MEDIA; saw: {states}")
        self.assertIn(PlayerState.STOPPED, player_states,
                       f"natural end-of-media never emitted PlayerState.STOPPED; saw: {player_states}")

    def test_stop_returns_bool(self):
        service, _, _ = self._service()
        self.assertIs(service.stop(), True)
        self.assertIs(service.stop(), False)


if __name__ == "__main__":
    unittest.main()
