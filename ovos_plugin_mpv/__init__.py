import threading
import time
from typing import List

from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_utils.log import LOG
from python_mpv_jsonipc import MPV


class OVOSMPVService(AudioBackend):
    def __init__(self, config, bus=None, name='ovos_mpv'):
        super(OVOSMPVService, self).__init__(config, bus, name)
        self.config = config
        self.bus = bus
        self.normal_volume = self.config.get('initial_volume', 100)
        self.low_volume = self.config.get('low_volume', 50)
        self._playback_time = 0
        self._last_sync = 0
        self.mpv = None
        self._seconds_to_error = 3
        self._started = threading.Event()

    ###################
    # mpv internals
    def init_mpv(self):
        self.mpv = MPV()
        self.mpv.volume = self.normal_volume
        self.mpv.bind_property_observer("eof-reached", self.handle_track_end)
        self.mpv.bind_property_observer("time-pos", self.update_playback_time)

        # TODO - doesnt seem to be called on bad tracks requested?
        self.mpv.bind_event("error", self.handle_mpv_error)

    def handle_track_end(self, key, val):
        if val is None:
            self._started.clear()
            self._started.wait(self._seconds_to_error)
            if not self._started.is_set():
                # assume an error/invalid uri
                # self._started should have been set by now!
                LOG.error(f"time out error! track should have started playing by now,"
                          f" is the uri valid? {self._now_playing}")
                self.handle_mpv_error("timeout")
            return
        if val is False:
            self._started.set()
            LOG.debug('MPV playback start')
            if self._track_start_callback:
                self._track_start_callback(self.track_info().get('name', "track"))
        else:
            LOG.debug('MPV playback ended')
            self._now_playing = None
            if self._track_start_callback:
                self._track_start_callback(None)

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
            return self.mpv.duration * 1000  # seconds to ms
        return 0

    def get_track_position(self):
        """
        get current position in milliseconds
        """
        if self.mpv:
            return self.mpv.time_pos * 1000  # seconds to ms
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

if __name__ == "__main__":
    from ovos_utils.fakebus import FakeBus

    m = OVOSMPVService({}, bus=FakeBus())
    m.load_track("https://INVALID")
    m.play()
    time.sleep(2)
    m.stop()
