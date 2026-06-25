import threading
import time
from typing import List

from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_plugin_manager.templates.media import (
    MediaBackend, AudioPlayerBackend, VideoPlayerBackend)
from ovos_utils.log import LOG
from ovos_utils.fakebus import FakeBus
from python_mpv_jsonipc import MPV


class MPVBaseService(MediaBackend):
    """Shared mpv engine.

    Holds all the playback logic (lazy ``MPV`` instance, event observers,
    play/stop/pause/seek/volume, position tracking). It is shared by both
    backend flavours so they drive one engine with no duplicated logic:

    * new ``ovos-media`` — :class:`MPVOCPAudioService` / :class:`MPVOCPVideoService`
      (``AudioPlayerBackend`` / ``VideoPlayerBackend``)
    * legacy ``ovos-audio`` — :class:`OVOSMPVService` (``AudioBackend``)
    """

    def __init__(self, config, bus=None):
        super().__init__(config, bus)
        self._init_mpv_state()

    def _init_mpv_state(self):
        """Set up mpv-specific instance state.

        Factored out of ``__init__`` so the legacy ``AudioBackend`` adapter
        (whose constructor takes a ``name``) can reuse it after its own base
        ``__init__`` has run. ``self.config``/``self.bus`` are already set by the
        framework base constructor.
        """
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
            except:  # too old OPM version / new MediaBackend without the helper
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


# --- new ovos-media backends (opm.media.audio / opm.media.video) ------------
class MPVOCPAudioService(AudioPlayerBackend, MPVBaseService):
    """mpv audio backend for the new ovos-media service."""

    def __init__(self, config, bus=None):
        super().__init__(config, bus)


class MPVOCPVideoService(VideoPlayerBackend, MPVBaseService):
    """mpv video backend for the new ovos-media service."""

    def __init__(self, config, bus=None):
        super().__init__(config, bus)


# --- legacy ovos-audio service backend (mycroft.plugin.audioservice) --------
class OVOSMPVService(MPVBaseService, AudioBackend):
    """mpv backend for the legacy ovos-audio service.

    ``MPVBaseService`` is listed first so its concrete playback methods satisfy
    ``AudioBackend``'s abstract methods (MRO order matters).
    """

    def __init__(self, config, bus=None, name='ovos_mpv'):
        AudioBackend.__init__(self, config, bus, name)
        self._init_mpv_state()


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
