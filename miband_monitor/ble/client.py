"""Public Mi Band 6 BLE client assembled from the domain mixins.

MiBand6Client is the same object the historical miband_client.MiBand6Client
was: same constructor signature, attribute names, defaults, exceptions and log
messages. Implementation lives in focused mixins so each file stays small:

- DiscoveryMixin / LinkMixin: find the band and open the BLE link
- MtuMixin / ListenerMixin: negotiate the ATT MTU, subscribe to 0x0017
- AuthStateMixin / AuthConnectMixin / AuthHandshakeMixin: chunked ECDH auth
- NotificationMixin / StreamMixin: live HR/steps/IMU streams and teardown

Test seams: _client_factory/_scanner_factory accept injected factories (the
simulator uses them) and _bleak_client_class records the real bleak class so
monkeypatching miband_monitor.ble.client.BleakClient is observable exactly like
the old miband_client.BleakClient monkeypatching. write_chunked_value is
imported into this module's namespace on purpose: the auth mixins resolve it
lazily through miband_monitor.ble.client so tests can patch it in one place.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from .. import bluez
from ..config.defaults import (
    DEFAULT_AUTH_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HR_KEEPALIVE_INTERVAL,
    DEFAULT_HR_SILENCE_HARD_SECONDS,
    DEFAULT_HR_SILENCE_SOFT_SECONDS,
    DEFAULT_HR_SOFT_REARM_MAX,
    DEFAULT_SCAN_TIMEOUT,
)
from .auth_connect import AuthConnectMixin
from .auth_handshake import AuthHandshakeMixin
from .auth_state import AuthStateMixin
from .backends import BleakClient, BleakScanner
from .battery import BatteryMixin
from .chunked import write_chunked_value  # noqa: F401  (lazy test/patch seam)
from .device_state import DeviceState, DeviceStateMachine
from .discovery import DiscoveryMixin
from .identity import normalize_auth_key
from .link import LinkMixin
from .listener import ListenerMixin
from .mtu import MtuMixin
from .notifications import NotificationMixin
from .protocol import MAX_REASSEMBLY_BYTES
from .streams import StreamMixin
from .time_sync import TimeSyncMixin
from .transactions import GattTransactionQueue, TransactionAborted, TransactionBuilder


@dataclass
class StreamCallbacks:
    """Optional consumers for the telemetry and band-history data streams."""

    heart_rate: Optional[Callable[[int], None]] = None
    steps: Optional[Callable[[dict], None]] = None
    imu: Optional[Callable[[dict], None]] = None
    history_spo2: Optional[Callable[[dict], None]] = None
    history_activity: Optional[Callable[[dict], None]] = None
    history_spo2_sleep: Optional[Callable[[dict], None]] = None
    history_sports: Optional[Callable[[dict], None]] = None
    history_stress: Optional[Callable[[dict], None]] = None


class MiBand6Client(
    DiscoveryMixin,
    LinkMixin,
    MtuMixin,
    ListenerMixin,
    AuthStateMixin,
    AuthConnectMixin,
    AuthHandshakeMixin,
    BatteryMixin,
    TimeSyncMixin,
    NotificationMixin,
    StreamMixin,
):
    """Handles BLE connection, chunked ECDH auth, and real-time data streaming."""

    def __init__(
        self,
        device_id: str,
        auth_key_hex: str,
        *,
        device_name: Optional[str] = None,
        mtu: Optional[int] = None,
        client_factory: Optional[Callable] = None,
        scanner_factory: Optional[Callable] = None,
        scan_timeout: float = DEFAULT_SCAN_TIMEOUT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        auth_timeout: float = DEFAULT_AUTH_TIMEOUT,
        direct_connect: bool = True,
        keepalive_interval: float = DEFAULT_HR_KEEPALIVE_INTERVAL,
        hr_silence_soft_seconds: float = DEFAULT_HR_SILENCE_SOFT_SECONDS,
        hr_silence_hard_seconds: float = DEFAULT_HR_SILENCE_HARD_SECONDS,
        hr_soft_rearm_max: int = DEFAULT_HR_SOFT_REARM_MAX,
    ) -> None:
        self.device_id = (device_id or "").strip()
        # Optional case-insensitive advertised-name match; works on platforms
        # (macOS) where the Bluetooth address is not exposed to applications.
        self.device_name = (device_name or "").strip() or None
        # Optional manual ATT MTU override; None means "ask the backend".
        self.mtu = mtu
        self.auth_key = normalize_auth_key(auth_key_hex)
        # Concrete bleak classes, captured once for the identity checks in the
        # mixins (real backend vs injected test/simulator factory).
        self._bleak_client_class = BleakClient
        self._client_factory = client_factory or BleakClient
        self._scanner_factory = scanner_factory or BleakScanner
        self.scan_timeout = scan_timeout
        self.connect_timeout = connect_timeout
        self.auth_timeout = auth_timeout
        # Linux only: try the band's already-bonded BlueZ object before scanning.
        self._direct_connect = bool(direct_connect)
        self._session_mtu: Optional[int] = None

        self.client: Optional[BleakClient] = None
        self.authenticated = False

        self._auth_event = asyncio.Event()
        self._auth_error: Optional[str] = None
        self._disconnected = asyncio.Event()
        self._closing = False

        self._hr_callback: Optional[Callable[[int], None]] = None
        self._steps_callback: Optional[Callable[[dict], None]] = None
        self._sensor_callback: Optional[Callable[[dict], None]] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._hr_active = False
        self._steps_active = False
        self._sensor_active = False
        self.keepalive_interval = max(0.01, float(keepalive_interval))
        self.hr_silence_soft_seconds = float(hr_silence_soft_seconds)
        self.hr_silence_hard_seconds = float(hr_silence_hard_seconds)
        self.hr_soft_rearm_max = max(0, int(hr_soft_rearm_max))
        self._last_hr_notify_at: Optional[float] = None
        self._hr_soft_rearm_count = 0
        self._battery_supported: Optional[bool] = None
        self._last_battery_level: Optional[int] = None
        #: Frame types seen on 0x0002 that are not accelerometer data (logged once).
        self._ignored_sensor_types: set[int] = set()

        # Chunked auth reassembly state (reset per connection).
        self._prv_key = b""
        self._pub_key = b""
        self._handle = 0
        self._reassemble_buf = bytearray(MAX_REASSEMBLY_BYTES)
        self._reassemble_ptr = 0
        self._expected_bytes = 0
        self._next_seq = 0
        self._step2_sent = False

        self._gatt_lock = asyncio.Lock()
        # B-5: transaction queue built on the SAME lock (no competing lock).
        # Existing write paths are unchanged; new code can group ordered GATT
        # actions into one abortable, serialized transaction.
        self.gatt_queue = GattTransactionQueue(self._gatt_lock)
        # B-4: device lifecycle state machine. The publish hook is attached by
        # the runner (to hub.publish_event) so BLE stays dashboard-agnostic.
        self.device_state = DeviceStateMachine()
        self._pairing_agent: Optional[bluez.BlueZPairingAgent] = None
        #: BlueZ device paths already marked Trusted in this session.
        self._trusted_paths: set[str] = set()
        self._reused_bluez_link = False
        self._unresolved_drops = 0
        self._stale_bond_reset_attempted = False
        self._auto_enable_pairing_agent = False
        self._last_scan_stats: Optional[dict[str, float | int]] = None

    # ------------------------------------------------------------- properties
    @property
    def mac_address(self) -> str:
        """Backwards-compatible alias for device_id."""
        return self.device_id

    @property
    def disconnected_event(self) -> asyncio.Event:
        """Event set when the BLE link drops unexpectedly (watchdog signal)."""
        return self._disconnected

    async def wait_until_disconnected(self) -> None:
        """Block until the link watchdog (or disconnect) fires."""
        await self._disconnected.wait()

    async def run_transaction(self, builder: TransactionBuilder) -> list:
        """Run an ordered GATT transaction through the serialized queue.

        The underlying bleak client is passed to each action; actions never
        re-acquire ``_gatt_lock`` themselves (the queue holds it for the group).
        A failed action aborts the whole transaction with
        :class:`TransactionAborted`; a transient link error is retried with
        bounded exponential backoff.
        """
        if self.client is None:
            raise RuntimeError("Client is not connected")
        return await self.gatt_queue.run(builder.build(), self.client)

    def attach_event_publisher(self, publish: Callable[[str, dict], None]) -> None:
        """Attach the shared event sink (``hub.publish_event``) for device events."""
        self.device_state._publish = publish

    def set_device_state(self, state: DeviceState) -> None:
        """Transition the device state machine (B-4)."""
        self.device_state.transition(state)
