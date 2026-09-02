import os
import unittest

from ovos_utils.fakebus import FakeBus
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_plugin_manager.templates.media import (
    AudioPlayerBackend, VideoPlayerBackend)

from ovos_plugin_mpv import (
    OVOSMPVService,
    MPVBaseService,
    MPVOCPAudioService,
    MPVOCPVideoService,
    MPVAudioPluginConfig,
    load_service,
)


class TestNewBackends(unittest.TestCase):
    """Dual-target: new ovos-media backends share the mpv engine."""

    def test_audio_backend_is_audioplayerbackend(self):
        svc = MPVOCPAudioService({}, bus=FakeBus())
        self.assertIsInstance(svc, AudioPlayerBackend)
        self.assertIsInstance(svc, MPVBaseService)
        # the shared engine state was initialised through the MRO
        self.assertIsNone(svc.mpv)
        self.assertEqual(svc.normal_volume, 100)

    def test_video_backend_is_videoplayerbackend(self):
        svc = MPVOCPVideoService({"initial_volume": 70}, bus=FakeBus())
        self.assertIsInstance(svc, VideoPlayerBackend)
        self.assertIsInstance(svc, MPVBaseService)
        self.assertEqual(svc.normal_volume, 70)

    def test_legacy_is_audiobackend(self):
        svc = OVOSMPVService({}, bus=FakeBus(), name='ovos_mpv')
        self.assertIsInstance(svc, AudioBackend)
        self.assertIsInstance(svc, MPVBaseService)

    def test_supported_uris_match(self):
        for cls in (MPVOCPAudioService, MPVOCPVideoService, OVOSMPVService):
            self.assertEqual(cls({}, bus=FakeBus()).supported_uris(),
                             ["file", "http", "https"])


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
