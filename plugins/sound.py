import asyncio
from typing import Callable, Coroutine

from protocol.datatypes import Float, Int, String, UnsignedByte
from proxhy.plugin import ProxhyPlugin


class SoundPluginState:
    note_to_pitch: Callable[[int], int]
    _play_sound: Callable[[str, float, int], None]
    _android_ringtone: Callable[[], Coroutine[None, None, None]]
    _iphone_ringtone: Callable[[], Coroutine[None, None, None]]


class SoundPlugin(ProxhyPlugin):
    def note_to_pitch(self, note: int) -> int:  # pyright: ignore[reportIncompatibleMethodOverride]
        """
        Convert Minecraft note-block semitone index to 1.8.9 pitch byte.
        note: 0–24 (F#3 → F#5)
        """
        pitch = round(63 * (2 ** ((note - 12) / 12)))
        return max(0, min(255, pitch))

    def _play_sound(self, sound: str, volume: float = 1.0, pitch: int = 63):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Play a sound effect at the player's position.

        Args:
            sound: The sound name (e.g. "random.click", "note.bd")
            volume: Volume level (1.0 = 100%)
            pitch: Pitch value (63 = normal, lower = deeper)
        """
        pos = self.gamestate.position
        self.client.send_packet(
            0x29,  # Sound Effect
            String.pack(sound),
            Int.pack(int(pos.x * 8)),
            Int.pack(int(pos.y * 8)),
            Int.pack(int(pos.z * 8)),
            Float.pack(volume),
            UnsignedByte.pack(pitch),
        )

    async def _android_ringtone(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        eighth = 0.2
        quarter = 0.4
        notes = [
            ([5], eighth),  # B3 - eighth note
            ([12], eighth),  # F#4 - eighth note
            ([17], eighth),  # B4 - eighth note
            ([16], quarter),  # A#4 - quarter note
            ([12], quarter),  # F#4 - quarter note
        ]
        for pitches, duration in notes:
            for note in pitches:
                self._play_sound("note.pling", pitch=self.note_to_pitch(note))
            await asyncio.sleep(duration)

    async def _iphone_ringtone(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        sixteenth = 0.2

        notes = [
            ([5], sixteenth),  # B3
            ([1], sixteenth),  # G3
            ([8, 13], sixteenth),  # D4 & G4
            ([1], sixteenth),  # G3
            ([8], sixteenth),  # D4
            ([10, 17], sixteenth),  # E4 & B4
            ([8], sixteenth),  # D4
            ([1], sixteenth),  # G3
            ([10, 17], sixteenth),  # E4 & B4
            ([8], sixteenth),  # D4
            ([1], sixteenth),  # G3
            ([8, 13], sixteenth),  # D4 & G4
        ]

        for pitches, duration in notes:
            for note in pitches:
                self._play_sound("note.pling", pitch=self.note_to_pitch(note))
            await asyncio.sleep(duration)
