import threading
import time
from typing import List, Optional

from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_plugin_manager.templates.media import (
    AudioPlayerBackend, MediaBackend, PlaybackEvent, VideoPlayerBackend)
from ovos_utils.log import LOG
from ovos_utils.fakebus import FakeBus
from python_mpv_jsonipc import MPV


class MPVMediaService(MediaBackend):
    """mpv engine for the ovos-media v2 backends.

    Only physical playback events observed on the mpv process are reported
    upstream via ``self.report`` - no bus state is emitted here, the daemon
    that owns this plugin drives the player state machine off those events.
    """

    can_seek = True
    can_pause = True

    def __init__(self, config, bus=None):
        super().__init__(config, bus)
        self.normal_volume = self.config.get('initial_volume', 100)
        self.low_volume = self.config.get('low_volume', 50)
        self.mpv: Optional[MPV] = None
        self._loaded_uri = None
        self._seconds_to_error = 5
        self._started = threading.Event()
        self._timeout_timer: Optional[threading.Timer] = None

    ###################
    # mpv internals
    def init_mpv(self):
        self.mpv = MPV()
        self.mpv.volume = self.normal_volume
        self.mpv.bind_property_observer("eof-reached", self._handle_eof_reached)
        self.mpv.bind_property_observer("pause", self._handle_pause_property)
        self.mpv.bind_event("end-file", self._handle_end_file)
        # TODO - doesnt seem to be called on bad tracks requested?
        self.mpv.bind_event("error", self._handle_mpv_error)

    def _check_start_timeout(self):
        """if playback doesnt start within the configured timeout, assume MPV error happened"""
        if not self._started.is_set():
            LOG.error(f"time out error! track should have started playing by now,"
                      f" is the uri valid? {self._loaded_uri}")
            self._handle_mpv_error("timeout")

    def _handle_eof_reached(self, key, val):
        """Only used to detect playback actually starting (val is False).

        End-of-playback is reported from ``_handle_end_file`` instead - the
        mpv "end-file" event carries the *reason* (eof/stop/error) that
        ``report_track_end`` needs to tell a natural end from an explicit
        ``stop()`` apart.
        """
        LOG.debug(f"MPV EOF event: {key} - {val}")
        if val is None and not self._started.is_set():
            # not started yet, arm a timeout so an invalid uri that never
            # starts playback still gets reported as an error
            if self._timeout_timer:
                self._timeout_timer.cancel()
            self._timeout_timer = threading.Timer(self._seconds_to_error,
                                                   self._check_start_timeout)
            self._timeout_timer.daemon = True
            self._timeout_timer.start()
            return

        if val is False:
            if self._timeout_timer:
                self._timeout_timer.cancel()
                self._timeout_timer = None
            self._started.set()
            LOG.debug('MPV playback start')
            self.report(PlaybackEvent.TRACK_START, uri=self._loaded_uri)

    def _handle_end_file(self, event_data):
        """Single call site for end-of-track reporting.

        mpv's "end-file" event carries *reason* (eof/stop/error/quit/
        redirect) - map a "error" reason to ``report_track_end``'s
        ``error`` kwarg, otherwise let the base class's explicit-stop flag
        (set by ``stop()``) decide between ``STOPPED`` and ``END_OF_MEDIA``.
        """
        LOG.debug(f"MPV end-file event: {event_data}")
        if self._timeout_timer:
            self._timeout_timer.cancel()
            self._timeout_timer = None
        self._started.clear()
        error = None
        if isinstance(event_data, dict) and event_data.get("reason") == "error":
            error = (event_data.get("file_error") or event_data.get("error")
                     or "mpv playback error")
        self.report_track_end(uri=self._loaded_uri, error=error)

    def _handle_pause_property(self, key, val):
        # mpv's own OSC/keyboard bindings can pause/resume outside of our
        # pause()/resume() calls - this observer is the only place that
        # actually knows the physical pause state, so it is the single
        # source of PAUSED/RESUMED reports regardless of who triggered them
        if not self._started.is_set():
            return
        if val:
            self.report(PlaybackEvent.PAUSED, uri=self._loaded_uri)
        else:
            self.report(PlaybackEvent.RESUMED, uri=self._loaded_uri)

    def _handle_mpv_error(self, *args, **kwargs):
        error = kwargs.get("error") or (str(args[0]) if args else "mpv error")
        self.report_track_end(uri=self._loaded_uri, error=str(error))

    ############
    # mandatory abstract methods
    def supported_uris(self) -> List[str]:
        """List of supported uri types.

        Returns:
            list: Supported uri's
        """
        return ['file', 'http', 'https']

    def load_track(self, uri: str, metadata: dict = None) -> bool:
        """Load a track for playback via mpv.

        Reports nothing on success or failure, per the base contract - the
        return value is the only signal.
        """
        self.meta = metadata or {}
        self._loaded_uri = uri
        if not self.mpv:
            self.init_mpv()
        self._started.clear()
        try:
            self.mpv.play(uri)
        except Exception:
            LOG.exception(f"mpv failed to load {uri}")
            return False
        return True

    def play(self):
        """ Play the loaded track using mpv. """
        if self.mpv:
            self.mpv.pause = False

    def _stop(self) -> bool:
        """ Stop mpv playback.

        Reports nothing itself - the resulting mpv "end-file" event (see
        ``_handle_end_file``) reports ``PlaybackEvent.STOPPED`` once it
        observes the explicit-stop flag ``stop()`` set.
        """
        if self.mpv:
            try:
                # best-effort: let mpv unload the file and fire its own
                # end-file(reason=stop) before we tear the process down
                self.mpv.command("stop")
            except Exception:
                pass
            self.mpv.terminate()
            self.mpv = None
            return True
        return False

    def pause(self):
        """ Pause mpv playback. """
        if self.mpv:
            self.mpv.pause = True

    def resume(self):
        """ Resume paused playback. """
        if self.mpv:
            self.mpv.pause = False

    def lower_volume(self):
        if self.mpv:
            self.mpv.volume = self.low_volume

    def restore_volume(self):
        if self.mpv:
            self.mpv.volume = self.normal_volume

    def track_info(self):
        """ Extract info of current track. """
        return dict(self.meta)

    def get_track_length(self) -> int:
        """
        getting the duration of the audio in milliseconds
        """
        if self.mpv:
            return int((self.mpv.duration or 0) * 1000)  # seconds to ms
        return -1

    def get_track_position(self) -> int:
        """
        get current position in milliseconds
        """
        if self.mpv:
            return int((self.mpv.time_pos or 0) * 1000)  # seconds to ms
        return -1

    def set_track_position(self, milliseconds):
        """
        go to position in milliseconds

          Args:
                milliseconds (int): number of milliseconds of final position
        """
        if self.mpv:
            self.mpv.command("seek", milliseconds / 1000, "absolute")


# --- new ovos-media backends (opm.media.audio / opm.media.video) ------------
class MPVOCPAudioService(MPVMediaService, AudioPlayerBackend):
    """mpv audio backend for the new ovos-media service."""


class MPVOCPVideoService(MPVMediaService, VideoPlayerBackend):
    """mpv video backend for the new ovos-media service."""


# --- legacy ovos-audio service backend (mycroft.plugin.audioservice) --------
class OVOSMPVService(AudioBackend):
    """mpv backend for the legacy ovos-audio service."""

    def __init__(self, config, bus=None, name='ovos_mpv'):
        super(OVOSMPVService, self).__init__(config, bus, name)
        self.normal_volume = self.config.get('initial_volume', 100)
        self.low_volume = self.config.get('low_volume', 50)
        self._playback_time = 0
        self._last_sync = 0
        self.mpv = None
        self._seconds_to_error = 5
        self._started = threading.Event()

    ###################
    # mpv internals
    def init_mpv(self):
        self.mpv = MPV()
        self.mpv.volume = self.normal_volume
        self.mpv.bind_property_observer("eof-reached", self.handle_track_eof_status)
        self.mpv.bind_property_observer("time-pos", self.update_playback_time)

        # TODO - doesnt seem to be called on bad tracks requested?
        self.mpv.bind_event("error", self.handle_mpv_error)
        self.bus.on("ovos.mpv.timeout_check", self.check_start_timeout)

    def check_start_timeout(self, message):
        """if playback doesnt start within the configured timeout, assume MPV error happened"""
        self._started.wait(self._seconds_to_error)
        if not self._started.is_set():
            # assume an error/invalid uri
            # self._started should have been set by now!
            LOG.error(f"time out error! track should have started playing by now,"
                      f" is the uri valid? {self._now_playing}")
            self.handle_mpv_error("timeout")

    def handle_track_eof_status(self, key, val):
        LOG.debug(f"MPV EOF event: {key} - {val}")
        if val is None and not self._started.is_set():
            # NOTE: a bus event is used otherwise we block the
            # MPV monitor thread with self._started.wait()
            # NOTE2: FakeBus doesnt use real events
            if not isinstance(self.bus, FakeBus):
                self.bus.emit(Message("ovos.mpv.timeout_check"))
            return

        if val is False:
            self._started.set()
            LOG.debug('MPV playback start')
            if self._track_start_callback:
                self._track_start_callback(self.track_info().get('name', "track"))
        elif self._started.is_set():
            LOG.debug('MPV playback ended')
            if self._track_start_callback:
                self._track_start_callback(None)
            self._started.clear()
            # natural end-of-media (mpv reached eof on its own, no stop()
            # requested by us) - ocp_stop() is idempotent (no-ops once
            # self._now_playing is None), so it is safe to call here even
            # when stop() already triggered it; this is the only path that
            # reports a *natural* end-of-media upward
            self.ocp_stop()

    def handle_mpv_error(self, *args, **kwargs):
        self.ocp_error()

    def update_playback_time(self, key, val):
        if val is None:
            return
        self._playback_time = val
        # this message is captured by ovos common play and used to sync the
        # seekbar
        if time.time() - self._last_sync > 2:
            # send event ~ every 2 s
            # the gui seems to lag a lot when sending messages too often,
            # gui expected to keep an internal fake progress bar and sync periodically
            self._last_sync = time.time()
            try:
                self.ocp_sync_playback(self._playback_time)
            except:  # too old OPM version
                self.bus.emit(Message("ovos.common_play.playback_time",
                                      {"position": self._playback_time,
                                       "length": self.get_track_length()}))

    ############
    # mandatory abstract methods
    @property
    def playback_time(self):
        """ in milliseconds """
        return self._playback_time

    def supported_uris(self) -> List[str]:
        """List of supported uri types.

        Returns:
            list: Supported uri's
        """
        return ['file', 'http', 'https']

    def play(self, repeat=False):
        """ Play playlist using mpv. """
        if not self.mpv:
            self.init_mpv()
        self._started.clear()
        self.mpv.play(self._now_playing)

    def stop(self):
        """ Stop mpv playback. """
        if self.mpv:
            self.mpv.terminate()
            self.mpv = None
            return True
        return False

    def pause(self):
        """ Pause mpv playback. """
        if self.mpv:
            self.mpv.pause = True

    def resume(self):
        """ Resume paused playback. """
        if self.mpv:
            self.mpv.pause = False

    def lower_volume(self):
        if self.mpv:
            self.mpv.volume = self.low_volume

    def restore_volume(self):
        if self.mpv:
            self.mpv.volume = self.normal_volume

    def track_info(self):
        """ Extract info of current track. """
        return {"uri": self._now_playing,
                "position": self._playback_time}

    def get_track_length(self):
        """
        getting the duration of the audio in milliseconds
        """
        if self.mpv:
            return (self.mpv.duration or 0) * 1000  # seconds to ms
        return 0

    def get_track_position(self):
        """
        get current position in milliseconds
        """
        if self.mpv:
            return (self.mpv.time_pos or 0) * 1000  # seconds to ms
        return 0

    def set_track_position(self, milliseconds):
        """
        go to position in milliseconds

          Args:
                milliseconds (int): number of milliseconds of final position
        """
        if self.mpv:
            self.mpv.command("seek", milliseconds)

    def seek_forward(self, seconds=1):
        """
        skip X seconds

          Args:
                seconds (int): number of seconds to seek, if negative rewind
        """
        if self.mpv:
            self.mpv.command("seek", seconds)

    def seek_backward(self, seconds=1):
        """
        rewind X seconds

          Args:
                seconds (int): number of seconds to seek, if negative rewind
        """
        if self.mpv:
            self.mpv.command("seek", seconds * -1)


def load_service(base_config, bus):
    backends = base_config.get('backends', [])
    services = [(b, backends[b]) for b in backends
                if backends[b]['type'] in ["mpv", 'ovos_mpv'] and
                backends[b].get('active', False)]
    instances = [OVOSMPVService(s[1], bus, s[0]) for s in services]
    return instances


MPVAudioPluginConfig = {
    "mpv": {
        "type": "ovos_mpv",
        "active": True
    }
}
