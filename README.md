# MPV OVOS Plugin

The MPV OVOS Plugin integrates MPV media player capabilities with the Open Voice OS (OVOS) ecosystem, providing an audio backend for playing various media formats.

## Features

- Supports playback of various audio formats.
- Provides basic playback controls: play, pause, stop, resume, seek forward, seek backward.
- Volume management with automatic volume adjustments.
- Integration with OVOS for media playback 

## Prerequisites

Ensure you have the following installed on your system:
- Python 3.6 or higher
- MPV media player
- Open Voice OS (OVOS) components


## Configuration

The MPV OVOS Plugin configuration can be set in your OVOS configuration file. Here is an example configuration:

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

## Usage

The plugin integrates with OVOS to handle audio playback. It supports the following functions:

- **play(repeat=False):** Play the current track.
- **stop():** Stop playback.
- **pause():** Pause playback.
- **resume():** Resume paused playback.
- **lower_volume():** Lower the volume to a predefined level.
- **restore_volume():** Restore the volume to the original level.
- **track_info():** Get information about the current track.
- **get_track_length():** Get the duration of the current track in milliseconds.
- **get_track_position():** Get the current playback position in milliseconds.
- **set_track_position(milliseconds):** Set the playback position in milliseconds.
- **seek_forward(seconds=1):** Seek forward by a specified number of seconds.
- **seek_backward(seconds=1):** Seek backward by a specified number of seconds.


## Troubleshooting

If you encounter any issues, ensure that:
- MPV is correctly installed and accessible.
- The plugin is installed.
- Your configuration file is correctly set up.
- If using containers ensure it is installed in `ovos-audio` container

For further assistance, refer to the official documentation or contact the plugin maintainers.

Check the logs to see what is happening, if specific streams are not playing verify that they play directly in MPV
