"""Full verb-cycle regression test for the v2 contract: driving
``MPVOCPAudioService`` through load/play/pause/resume/stop must never emit a
single bus message - all playback state flows through ``report()`` to
whatever reporter the daemon bound, never through ``self.bus``.

``ovoscope[media]``'s ``OCPPlayerHarness`` drives a real ``OCPMediaPlayer``,
which has not been ported to the MediaBackend v2 contract yet, so it cannot
be used here without producing false failures unrelated to this plugin; this
test exercises the plugin directly instead. The mpv engine itself (libmpv via
``python_mpv_jsonipc.MPV``) is mocked - no real player/binary is required or
available in this environment.
"""
import unittest
from unittest.mock import MagicMock, patch

import ovos_plugin_mpv
from ovos_plugin_manager.templates.media import PlaybackEvent
from ovos_utils.fakebus import FakeBus

from ovos_plugin_mpv import MPVOCPAudioService

URI = "http://example.com/song.mp3"


class TestFullVerbCycleEmitsNoBusState(unittest.TestCase):
    def test_load_play_pause_resume_stop_never_touches_the_bus(self):
        bus = FakeBus()
        emitted = []
        bus.emit = lambda message: emitted.append(message)

        events = []
        with patch.object(ovos_plugin_mpv, "MPV", MagicMock()):
            svc = MPVOCPAudioService({}, bus=bus)
            svc.bind_event_reporter(lambda event, **data: events.append((event, data)))

            self.assertTrue(svc.load_track(URI, {"title": "song"}))
            svc.play()
            svc._handle_eof_reached("eof-reached", False)  # mpv: playback started

            svc.pause()
            svc._handle_pause_property("pause", True)  # mpv: paused

            svc.resume()
            svc._handle_pause_property("pause", False)  # mpv: resumed

            svc.stop()
            svc._handle_end_file({"reason": "stop"})  # mpv: end-file(stop)

        self.assertEqual(emitted, [],
                         f"backend must never emit on self.bus, saw: {emitted}")
        self.assertEqual([e for e, _ in events],
                         [PlaybackEvent.TRACK_START,
                          PlaybackEvent.PAUSED,
                          PlaybackEvent.RESUMED,
                          PlaybackEvent.STOPPED])
        for _, data in events:
            self.assertEqual(data.get("uri"), URI)

    def test_backend_is_the_real_mpv_plugin(self):
        with patch.object(ovos_plugin_mpv, "MPV", MagicMock()):
            svc = MPVOCPAudioService({}, bus=FakeBus())
            self.assertIsInstance(svc, MPVOCPAudioService)
            self.assertEqual(svc.supported_uris(), ["file", "http", "https"])


if __name__ == "__main__":
    unittest.main()
