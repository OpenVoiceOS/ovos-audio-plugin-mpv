"""End-to-end tests: drive the real mpv OCP backend through a real
``OCPMediaPlayer`` on a FakeBus via ovoscope's media harness.

The mpv *engine* (libmpv via ``python_mpv_jsonipc.MPV``) is mocked so no real
player/binary is needed, but everything else is real: the OCP player routes the
play/pause/stop/seek requests to ``MPVOCPAudioService`` exactly as ovos-media
would at runtime.

Requires ``ovoscope[media]`` (pulls ovos-media).
"""
import unittest
from unittest.mock import MagicMock, patch

try:
    from ovoscope import OCPPlayerHarness
    from ovos_utils.ocp import MediaEntry, PlaybackType, PlayerState
    HAVE_HARNESS = True
except Exception:
    HAVE_HARNESS = False

import ovos_plugin_mpv
from ovos_plugin_mpv import MPVOCPAudioService

URI = "http://example.com/song.mp3"


def _factory(bus):
    """Build the real mpv audio backend for injection into the OCP player."""
    return MPVOCPAudioService({}, bus)


@unittest.skipUnless(HAVE_HARNESS, "ovoscope[media] not installed")
class TestMPVEndToEnd(unittest.TestCase):
    def test_play_pause_resume_stop_through_ocp(self):
        with patch.object(ovos_plugin_mpv, "MPV", MagicMock()):
            with OCPPlayerHarness(backend_factory=_factory) as h:
                entry = MediaEntry(uri=URI, playback=PlaybackType.AUDIO)

                h.play(entry)
                h.assert_player_state(PlayerState.PLAYING)
                h.assert_now_playing_uri(URI)
                # the real backend actually started its (mocked) mpv engine
                self.assertIsNotNone(h.backend.mpv)

                h.pause()
                h.assert_player_state(PlayerState.PAUSED)

                h.resume()
                h.assert_player_state(PlayerState.PLAYING)

                h.stop()
                h.assert_player_state(PlayerState.STOPPED)

    def test_backend_is_the_real_mpv_plugin(self):
        with patch.object(ovos_plugin_mpv, "MPV", MagicMock()):
            with OCPPlayerHarness(backend_factory=_factory) as h:
                self.assertIsInstance(h.backend, MPVOCPAudioService)
                self.assertEqual(h.backend.supported_uris(),
                                 ["file", "http", "https"])


if __name__ == "__main__":
    unittest.main()
