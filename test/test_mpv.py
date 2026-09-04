import os
import unittest
from unittest.mock import MagicMock

from ovos_utils.fakebus import FakeBus
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_plugin_manager.templates.media import (
    AudioPlayerBackend, PlaybackEvent, VideoPlayerBackend)

from ovos_plugin_mpv import (
    OVOSMPVService,
    MPVMediaService,
    MPVOCPAudioService,
    MPVOCPVideoService,
    MPVAudioPluginConfig,
    load_service,
)


class RecordingReporter:
    """Collects every ``report(event, **data)`` call for assertions."""

    def __init__(self):
        self.events = []

    def __call__(self, event, **data):
        self.events.append((event, data))


class TestNewBackends(unittest.TestCase):
    """New ovos-media v2 backends share the mpv engine."""

    def test_audio_backend_is_audioplayerbackend(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        self.assertIsInstance(svc, AudioPlayerBackend)
        self.assertIsInstance(svc, MPVMediaService)
        self.assertIsNone(svc.mpv)
        self.assertEqual(svc.normal_volume, 100)
        self.assertTrue(svc.can_seek)
        self.assertTrue(svc.can_pause)

    def test_video_backend_is_videoplayerbackend(self):
        svc = MPVOCPVideoService({"initial_volume": 70}, bus=FakeBus())
        self.assertIsInstance(svc, VideoPlayerBackend)
        self.assertIsInstance(svc, MPVMediaService)
        self.assertEqual(svc.normal_volume, 70)

    def test_legacy_is_audiobackend(self):
        svc = OVOSMPVService({}, bus=FakeBus(), name='ovos_mpv')
        self.assertIsInstance(svc, AudioBackend)
        # the legacy backend is untouched by the v2 port
        self.assertNotIsInstance(svc, MPVMediaService)

    def test_supported_uris_match(self):
        for cls in (MPVOCPAudioService, MPVOCPVideoService, OVOSMPVService):
            self.assertEqual(cls({}, bus=FakeBus()).supported_uris(),
                             ["file", "http", "https"])

    def test_load_track_returns_bool_and_reports_nothing(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        self.assertIs(svc.load_track("file:///tmp/track.wav"), True)
        self.assertEqual(svc._loaded_uri, "file:///tmp/track.wav")
        self.assertEqual(reporter.events, [])

    def test_load_track_failure_returns_false_and_reports_nothing(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        svc.mpv.play.side_effect = RuntimeError("bad uri")

        self.assertIs(svc.load_track("not-a-uri"), False)
        # load_track reports nothing per the base contract - the bool
        # return is the only signal, the daemon owns the transition
        self.assertEqual(reporter.events, [])

    def test_track_start_reported_on_eof_property_false(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        svc._loaded_uri = "http://example.com/song.mp3"

        svc._handle_eof_reached("eof-reached", False)

        self.assertEqual(reporter.events,
                         [(PlaybackEvent.TRACK_START,
                           {"uri": "http://example.com/song.mp3"})])
        self.assertTrue(svc._started.is_set())

    def test_end_file_eof_without_stop_reports_end_of_media(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        svc._loaded_uri = "http://example.com/song.mp3"
        svc._started.set()

        # mpv's end-file event fires with reason "eof" for a track that
        # finished playing on its own, with no stop() ever called
        svc._handle_end_file({"reason": "eof"})

        self.assertEqual(reporter.events,
                         [(PlaybackEvent.END_OF_MEDIA,
                           {"uri": "http://example.com/song.mp3"})])
        self.assertFalse(svc._started.is_set())
        self.assertFalse(svc._stop_requested)

    def test_stop_then_end_file_reports_stopped(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        svc._loaded_uri = "http://example.com/song.mp3"
        svc._started.set()

        svc.stop()  # sets _stop_requested via the base class's stop()
        # mpv's real end-file(reason=stop) event, triggered by the
        # "stop" command _stop() issues before tearing the process down
        svc._handle_end_file({"reason": "stop"})

        self.assertEqual(reporter.events,
                         [(PlaybackEvent.STOPPED,
                           {"uri": "http://example.com/song.mp3"})])
        self.assertFalse(svc._stop_requested)

    def test_end_file_error_reason_reports_error_with_uri(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        svc._loaded_uri = "http://example.com/song.mp3"
        svc._started.set()

        svc._handle_end_file({"reason": "error", "file_error": "loading failed"})

        self.assertEqual(reporter.events,
                         [(PlaybackEvent.ERROR,
                           {"uri": "http://example.com/song.mp3",
                            "error": "loading failed"})])
        # a nonzero/errored engine end is ERROR, never END_OF_MEDIA - even
        # if stop() happened to have been requested
        self.assertFalse(svc._stop_requested)

    def test_end_file_error_reason_beats_pending_stop_request(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        svc._loaded_uri = "http://example.com/song.mp3"
        svc._started.set()

        svc.stop()
        svc._handle_end_file({"reason": "error", "file_error": "device lost"})

        self.assertEqual(reporter.events,
                         [(PlaybackEvent.ERROR,
                           {"uri": "http://example.com/song.mp3",
                            "error": "device lost"})])

    def test_external_pause_and_resume_are_reported(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()
        svc._loaded_uri = "http://example.com/song.mp3"
        svc._started.set()

        # mpv's own OSC/keyboard bindings toggle the "pause" property
        # directly, with no pause()/resume() call from the daemon
        svc._handle_pause_property("pause", True)
        svc._handle_pause_property("pause", False)

        self.assertEqual(reporter.events,
                         [(PlaybackEvent.PAUSED,
                           {"uri": "http://example.com/song.mp3"}),
                          (PlaybackEvent.RESUMED,
                           {"uri": "http://example.com/song.mp3"})])

    def test_pause_property_ignored_before_playback_started(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc.mpv = MagicMock()

        svc._handle_pause_property("pause", True)

        self.assertEqual(reporter.events, [])

    def test_mpv_error_event_reports_error_via_report_track_end(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        reporter = RecordingReporter()
        svc.bind_event_reporter(reporter)
        svc._loaded_uri = "http://example.com/song.mp3"

        svc._handle_mpv_error(error="playback failure")

        self.assertEqual(reporter.events,
                         [(PlaybackEvent.ERROR,
                           {"uri": "http://example.com/song.mp3",
                            "error": "playback failure"})])
        self.assertFalse(svc._stop_requested)

    def test_stop_is_the_public_contract_and_delegates_to__stop(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        svc.mpv = MagicMock()
        self.assertFalse(svc._stop_requested)
        self.assertIs(svc.stop(), True)
        self.assertTrue(svc._stop_requested)
        self.assertIs(svc.stop(), False)
        self.assertTrue(hasattr(svc, "_stop"))

    def test_track_metrics_without_mpv(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        self.assertEqual(svc.get_track_length(), -1)
        self.assertEqual(svc.get_track_position(), -1)

    def test_control_methods_without_mpv_are_safe(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        svc.pause()
        svc.resume()
        svc.lower_volume()
        svc.restore_volume()
        svc.set_track_position(1000)
        self.assertIsNone(svc.mpv)


class TestEntryPoints(unittest.TestCase):
    def test_pyproject_declares_new_and_legacy_groups(self):
        here = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(here, "pyproject.toml")) as f:
            src = f.read()
        self.assertIn("opm.media.audio", src)
        self.assertIn("opm.media.video", src)
        self.assertIn("mycroft.plugin.audioservice", src)
        self.assertIn("MPVOCPAudioService", src)


class TestMPVAudioPluginConfig(unittest.TestCase):
    def test_config_shape(self):
        self.assertIn("mpv", MPVAudioPluginConfig)
        cfg = MPVAudioPluginConfig["mpv"]
        self.assertEqual(cfg["type"], "ovos_mpv")
        self.assertTrue(cfg["active"])


class TestOVOSMPVService(unittest.TestCase):
    """Legacy ovos-audio backend - untouched by the v2 port."""

    def setUp(self):
        self.bus = FakeBus()
        self.service = OVOSMPVService({}, self.bus)

    def test_default_volumes(self):
        self.assertEqual(self.service.normal_volume, 100)
        self.assertEqual(self.service.low_volume, 50)

    def test_config_volumes(self):
        service = OVOSMPVService(
            {"initial_volume": 80, "low_volume": 20}, self.bus
        )
        self.assertEqual(service.normal_volume, 80)
        self.assertEqual(service.low_volume, 20)

    def test_supported_uris(self):
        self.assertEqual(
            self.service.supported_uris(), ["file", "http", "https"]
        )

    def test_initial_state(self):
        self.assertIsNone(self.service.mpv)
        self.assertEqual(self.service.playback_time, 0)
        self.assertFalse(self.service._started.is_set())

    def test_track_info(self):
        self.service._now_playing = "http://example.com/track.mp3"
        info = self.service.track_info()
        self.assertEqual(info["uri"], "http://example.com/track.mp3")
        self.assertEqual(info["position"], 0)

    def test_track_metrics_without_mpv(self):
        # with no live mpv instance these must be safe no-ops / zero
        self.assertEqual(self.service.get_track_length(), 0)
        self.assertEqual(self.service.get_track_position(), 0)

    def test_control_methods_without_mpv_are_safe(self):
        # none of these should raise when mpv is not initialized
        self.service.stop()
        self.service.pause()
        self.service.resume()
        self.service.lower_volume()
        self.service.restore_volume()
        self.service.set_track_position(1000)
        self.service.seek_forward(5)
        self.service.seek_backward(5)
        self.assertIsNone(self.service.mpv)


class TestLoadService(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()

    def test_load_active_backend(self):
        config = {
            "backends": {
                "my_mpv": {"type": "ovos_mpv", "active": True},
            }
        }
        instances = load_service(config, self.bus)
        self.assertEqual(len(instances), 1)
        self.assertIsInstance(instances[0], OVOSMPVService)
        self.assertEqual(instances[0].name, "my_mpv")

    def test_skip_inactive_backend(self):
        config = {
            "backends": {
                "my_mpv": {"type": "ovos_mpv", "active": False},
            }
        }
        self.assertEqual(load_service(config, self.bus), [])

    def test_skip_other_backend_types(self):
        config = {
            "backends": {
                "other": {"type": "vlc", "active": True},
            }
        }
        self.assertEqual(load_service(config, self.bus), [])

    def test_mpv_type_alias(self):
        config = {
            "backends": {
                "legacy": {"type": "mpv", "active": True},
            }
        }
        instances = load_service(config, self.bus)
        self.assertEqual(len(instances), 1)

    def test_no_backends(self):
        self.assertEqual(load_service({}, self.bus), [])


if __name__ == "__main__":
    unittest.main()
