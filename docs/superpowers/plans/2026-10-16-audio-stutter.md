# Audio stutter diagnosis

> Historical evidence only. This dated plan is retained read-only as a record, not current operating instructions. Deployment addresses and device identities are examples. Current guidance: root README and docs/architecture.md.

User reports intermittent reply audio after display fixes. Passive 40s conversation capture shows 20 UDP sequence gaps, 42 missing 60ms frames (2.52s), worst gap 6 frames (360ms), plus one late frame. No decoder/I2S error in sample. Current configuration has static Wi-Fi RX=3, dynamic RX=6, UDP receive mailbox=6; bootstrap RSSI=-38dBm and conversation internal SRAM about132KB (minimum117KB).

Hypothesis: the small receive pipeline drops bursty audio packets before the low-priority UDP receive task drains them. Test one capacity change while leaving codec, playback queues, SPI, AEC, and transport unchanged. Increase board variant RX to8/32, BA window6, UDP and TCPIP mailboxes32. Add a single per-channel diagnostic showing current RSSI/power-saving mode and compiled capacities; no secrets.

- [x] Capture baseline and quantify gaps.
- [x] Configure through ESP-IDF Kconfig server, verify only intended network settings change.
- [x] Build, review and app-only flash candidate1; device booted with RX8/32 and connected.
- [x] Obtain user listening feedback: 明显更顺畅. Post-update packet loss remains unquantified because captured sessions contained no speaking state.
- [x] Record result: user confirmed improved audio. Retain candidate1; do not claim zero packet loss or fully proven root cause.

Candidate1: 3,238,592 bytes, SHA256 6b0b14786193da851115fb2294d0cb9df7cd07f54b874bd76c6c5ecdae9bfb78; esptool write hash verified. First 55s post-update capture contained Wi-Fi reconnect/activation but no speaking state, so zero gap warnings is not evidence of an audio improvement. Await an actual long reply and user feedback before claiming a fix.

User subsequently confirmed reply audio is 明显更顺畅. This verifies perceived improvement, not an exact post-update packet-loss rate.
