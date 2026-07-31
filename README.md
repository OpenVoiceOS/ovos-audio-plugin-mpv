# ovos-media-plugin-mpv

`ovos-media-plugin-mpv` is an audio and video playback plugin for [OpenVoiceOS](https://github.com/OpenVoiceOS) (OVOS). It drives the [mpv](https://mpv.io) media player through `python-mpv-jsonipc` and exposes it as a playback backend for [ovos-media](https://github.com/OpenVoiceOS/ovos-media) and the legacy `ovos-audio` service.

## Install

Install the plugin with pip:

```bash
pip install ovos-media-plugin-mpv
```

The plugin needs the `mpv` media player installed and available on the system.

## Usage

OVOS discovers the plugin through entry points, so no code changes are needed. Enable and configure it in your OVOS configuration file:

```json
{
  "backends": {
    "mpv": {
      "type": "ovos_mpv",
      "active": true,
      "initial_volume": 100,
      "low_volume": 50
    }
  }
}
```

`initial_volume` sets the starting volume. `low_volume` sets the volume used while the assistant lowers playback, for example to speak over a track.

The plugin registers under two entry-point groups, so it works with both stacks:

- `opm.media.audio` / `opm.media.video`, used by the current `ovos-media` service.
- `mycroft.plugin.audioservice`, used by the legacy `ovos-audio` service.

Once active, the backend exposes the standard OVOS media-backend API: play, stop, pause, resume, seek forward, seek backward, track position, and track length.

## Troubleshooting

- Confirm mpv is installed and runs directly from the command line.
- Confirm the plugin package is installed in the same environment as the OVOS service (in containers, install it inside the `ovos-audio` container).
- Confirm the backend is active in the configuration file.
- Check the service logs. If a stream does not play, confirm the stream plays directly in mpv.

## Related projects

- [OpenVoiceOS/ovos-media](https://github.com/OpenVoiceOS/ovos-media), the media service that loads this backend.
- [OpenVoiceOS/ovos-media-plugin-vlc](https://github.com/OpenVoiceOS/ovos-media-plugin-vlc), a sibling backend that uses VLC.
- [OpenVoiceOS/ovos-media-plugin-ffplay](https://github.com/OpenVoiceOS/ovos-media-plugin-ffplay), a sibling backend that uses ffplay.
- [OpenVoiceOS/ovos-media-plugin-mplayer](https://github.com/OpenVoiceOS/ovos-media-plugin-mplayer), a sibling backend that uses mplayer.

## License

Apache-2.0. See [LICENSE](LICENSE).
