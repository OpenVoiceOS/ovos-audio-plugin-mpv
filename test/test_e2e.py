"""End-to-end tests: drive the real mpv OCP backend through a real
``OCPMediaPlayer`` on a FakeBus via ovoscope's media harness.

The mpv *engine* (libmpv via ``python_mpv_jsonipc.MPV``) is mocked so no real
player/binary is needed, but everything else is real: the OCP player routes the
play/pause/stop/seek requests to ``MPVOCPAudioService`` exactly as ovos-media
would at runtime.

``OCPPlayerHarness`` dispatches bus messages on a background worker thread;
``OCPMediaPlayer.play()`` sets ``PlayerState.PLAYING`` only once its own
(async) dispatch of the play request settles, *after* the harness's fixed
``time.sleep(0.05)``. On a loaded runner that can outlast the sleep, so a
follow-up ``pause()`` (which sets ``PlayerState.PAUSED`` immediately) can
race - and lose to - that still-in-flight ``PLAYING`` assignment, clobbering
the pause a moment later (observed intermittently in CI:
"Expected PlayerState.PAUSED, got PlayerState.PLAYING", not reproducible
locally). Poll for the expected state (bounded) between steps instead of
trusting the harness's fixed sleep to close that race.

Requires ``ovoscope[media]`` (pulls ovos-media).
"""
import time
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


def _wait_for_state(h, state: PlayerState, timeout: float = 5.0) -> None:
    """Poll for *state*, bounded by *timeout*.

    Closes the race between OCPMediaPlayer's own (async) trailing
    ``set_player_state`` calls and ours - see module docstring.
    """
    deadline = time.time() + timeout
    while time.time() < deadline and h.player.state != state:
        time.sleep(0.01)


@unittest.skipUnless(HAVE_HARNESS, "ovoscope[media] not installed")
class TestMPVEndToEnd(unittest.TestCase):
    def test_play_pause_resume_stop_through_ocp(self):
        with patch.object(ovos_plugin_mpv, "MPV", MagicMock()):
            with OCPPlayerHarness(backend_factory=_factory) as h:
                entry = MediaEntry(uri=URI, playback=PlaybackType.AUDIO)

                h.play(entry)
                _wait_for_state(h, PlayerState.PLAYING)
                h.assert_player_state(PlayerState.PLAYING)
                h.assert_now_playing_uri(URI)
                # the real backend actually started its (mocked) mpv engine
                self.assertIsNotNone(h.backend.mpv)

                h.pause()
                _wait_for_state(h, PlayerState.PAUSED)
                h.assert_player_state(PlayerState.PAUSED)

                h.resume()
                _wait_for_state(h, PlayerState.PLAYING)
                h.assert_player_state(PlayerState.PLAYING)

                h.stop()
                _wait_for_state(h, PlayerState.STOPPED)
                h.assert_player_state(PlayerState.STOPPED)

    def test_backend_is_the_real_mpv_plugin(self):
        with patch.object(ovos_plugin_mpv, "MPV", MagicMock()):
            with OCPPlayerHarness(backend_factory=_factory) as h:
                self.assertIsInstance(h.backend, MPVOCPAudioService)
                self.assertEqual(h.backend.supported_uris(),
                                 ["file", "http", "https"])


if __name__ == "__main__":
    unittest.main()
