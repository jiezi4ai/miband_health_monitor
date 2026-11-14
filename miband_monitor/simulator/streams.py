"""Notification-stream scheduling for heart rate, real-time steps and raw IMU.

Subscribing to the steps characteristic immediately replays two packets; the
raw-sensor stream only starts after the client writes a sensor-start command.
Timers are scheduled through the simulated band's event loop so all frames flow
through the same notify path a real GATT layer would use.
"""

from __future__ import annotations

from miband_monitor.ble import (
    UUID_CHAR_HR_MEASUREMENT,
    UUID_CHAR_RAW_SENSOR_DATA,
    UUID_CHAR_STEPS,
)


class StreamMixin:
    """Notification-stream half of the simulated band state machine."""

    # ------------------------------------------------------------ streams
    def _hr_freeze_active(self) -> bool:
        if self.freeze_hr_after is None:
            return False
        if self.freeze_on_connections is not None:
            return self.connect_count in self.freeze_on_connections
        return True

    def _schedule_next_hr_tick(self, delay: float) -> None:
        if self._loop is not None and self.connected and self._hr_started:
            self._timers.append(self._loop.call_later(delay, self._emit_hr_step))

    def _emit_hr_step(self) -> None:
        if not self.connected or not self._hr_started or self._hr_frozen:
            return
        if self._hr_freeze_active() and self._hr_emitted_in_conn >= int(self.freeze_hr_after):
            self._hr_frozen = True
            return
        if not self.hr_values:
            return
        bpm = self.hr_values[self._hr_tick_index % len(self.hr_values)]
        self._hr_tick_index += 1
        self._hr_emitted_in_conn += 1
        self._emit(UUID_CHAR_HR_MEASUREMENT, bytes([0x00, bpm & 0xFF]))
        if self.continuous_interval is not None and self.continuous_interval > 0:
            self._schedule_next_hr_tick(float(self.continuous_interval))

    def _on_heart_rate_control(self, data: bytes) -> None:
        if data == b"\x15\x01\x01":
            if self._hr_started:
                if self.resurrect_on_rearm and self._hr_frozen:
                    self._hr_frozen = False
                    self._hr_emitted_in_conn = 0
                    if self.continuous_interval is not None and self.continuous_interval > 0:
                        self._schedule_next_hr_tick(float(self.continuous_interval))
                    else:
                        self._schedule_next_hr_tick(0.02)
                return
            self._hr_started = True
            self._hr_frozen = False
            self._hr_tick_index = 0
            if self.continuous_interval is not None and self.continuous_interval > 0:
                self._schedule_next_hr_tick(0.02)
            else:
                for index, _bpm in enumerate(self.hr_values):
                    self._timers.append(
                        self._loop.call_later(  # type: ignore[union-attr]
                            0.02 * (index + 1),
                            self._emit_hr_step,
                        )
                    )
        elif data[:2] in (b"\x15\x01", b"\x15\x02"):
            self._hr_started = False
            self._hr_frozen = False

    def _on_sensor_control(self, data: bytes) -> None:
        if data == b"\x03":
            self._sensor_started = False
        elif data and data[0] in (0x01, 0x02):
            self._sensor_started = True

    def _schedule_steps(self) -> None:
        if self._steps_scheduled or not self.steps_packets:
            return
        self._steps_scheduled = True
        for index, packet in enumerate(self.steps_packets):
            self._timers.append(
                self._loop.call_later(  # type: ignore[union-attr]
                    0.01 * (index + 1), self._emit, UUID_CHAR_STEPS, packet
                )
            )

    def _schedule_imu(self) -> None:
        if self._imu_scheduled or not self.imu_packets:
            return
        self._imu_scheduled = True
        for index, packet in enumerate(self.imu_packets):
            self._timers.append(
                self._loop.call_later(  # type: ignore[union-attr]
                    0.01 * (index + 1), self._emit, UUID_CHAR_RAW_SENSOR_DATA, packet
                )
            )
