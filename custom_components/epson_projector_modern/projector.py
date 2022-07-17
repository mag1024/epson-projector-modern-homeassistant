import asyncio
import logging
from datetime import datetime, timedelta

LOG = logging.getLogger(__name__)

class COMMAND:
    POWER = "PWR"
    SOURCE = "SOURCE"
    SOURCE_LIST = "SOURCELIST"
    LENS_POSSITION = "POPLP"
    SERIAL_NUMBER = "SNO"

STATUS_OK = 0x20

STATUS = {
    0x20: "OK Normal termination",
    0x40: "Bad Request Request cannot be understood as its grammar is wrong.",
    0x41: "Unauthorized. Password is required.",
    0x43: "Forbidden Password is wrong.",
    0x45: "Request not allowed Disallowed type request.",
    0x53: "Service Unavailable The projector is BUSY, etc.",
    0x55: "Protocol Version Not Supported",
}

POWER_STATUS = {
    0: "Standby / Network off",
    1: "Power on",
    2: "Warm up",
    3: "Cooling down",
    4: "Standby / Network on",
    5: "Abnormal standby",
}

EVENT_TO_POWER_STATUS = {
    1: 4, # standby
    2: 2, # warmup
    3: 1, # normal
    4: 3, # cooldown
}

def _power_status_str(status):
    return POWER_STATUS[status] if status else "Unknown"

class CommandError(Exception):
    pass

class Connection(asyncio.Protocol):
    ESCVPNET = 'ESC/VP.net'
    IMEVENT = 'IMEVENT'
    SEND_TERMINATOR = '\r\n'
    RECV_TERMINATOR = ':'

    def __init__(self, on_imevent, on_disconnect):
        self._on_imevent = on_imevent
        self._on_disconnect = on_disconnect
        self._transport = None

        self._request_lock = asyncio.Lock()
        self._pending_result = None

        self._buffer = ""
        self._last_response = None

    def connection_made(self, transport):
        self._transport = transport

    def connection_lost(self, exc):
        LOG.info("Connection terminated.")
        if result := self._pending_result: result.set_exception(CommandError())
        self._buffer = ""
        self._on_disconnect()

    def data_received(self, data):
        LOG.debug("<< %s", data)
        self._last_response = datetime.now()
        self._buffer += data.decode()
        self._maybe_consume_buffer()

    async def send_command(self, command, terminator = SEND_TERMINATOR, delay=0) -> str:
        async with self._request_lock:
            self._pending_result = asyncio.get_running_loop().create_future()
            request = (command + terminator).encode('ascii')
            LOG.debug(">> %s", request)
            self._transport.write(request)
            try:
                data = await self._pending_result
                if delay: await asyncio.sleep(delay)
                return data
            finally:
                self._pending_result = None

    async def handshake(self):
        resp = await self.send_command(self.ESCVPNET, '\x10\x03\x00\x00\x00\x00')
        status = ord(resp[14])
        if status != STATUS_OK: raise RuntimeError("Handshake error: " + STATUS[status])

    def close(self):
        if self._transport:
            self._transport.abort()
            self._transport = None

    def last_response_age(self): return datetime.now() - self._last_response

    def _maybe_consume_buffer(self):
        if self._buffer.startswith(self.ESCVPNET):
            if len(self._buffer) < 16: return
            # insert a terminator so it can be processed like a regular command
            self._buffer = self._buffer[0:16] + self.RECV_TERMINATOR + self._buffer[16:]

        while ':' in self._buffer:
            (resp, self._buffer) = self._buffer.split(':', 1)
            if len(resp) and resp[-1] == '\r': resp = resp[0:-1]
            if resp.startswith(self.IMEVENT):
                self._on_imevent(resp[len(self.IMEVENT) + 1:])
                return

            if result := self._pending_result:
                if resp == 'ERR': result.set_exception(CommandError())
                else: result.set_result(resp)
            else:
                LOG.warning('Unexpected response: ' + resp)


class Projector:
    def __init__(self, host, port = 3629):
        self._host = host
        self._port = port

        self.serial_number = None
        self._power_status = None
        self._source = None
        self._sources_dict = {}

        self._connection = None
        self._monitor_connection_task = None

    async def connect(self):
        loop = asyncio.get_running_loop()
        self._monitor_connection_task = loop.create_task(self._monitor_connection())
        await self._connect()

    async def disconnect(self):
        if self._monitor_connection_task:
            self._monitor_connection_task.cancel()
            try:
                await self._monitor_connection_task
            except asyncio.CancelledError:
                pass
            finally:
                self._monitor_connection_task = None
        if self._connection: self._connection.close()

    @property
    def power(self) -> bool: return self._power_status in [1, 2]
    @property
    def connection_ok(self) -> bool: return self._connection != None
    @property
    def source_list(self) -> [str]: return list(self._sources_dict.values())
    @property
    def source(self) -> str:
        try: return self._sources_dict[self._source]
        except: return 'unknown'

    async def set_power(self, on_off):
        # if the projector receives other commands shortly after the poweroff,
        # it gets upset, and the network interface becomes wedged in a way that
        # doesn't recover even if the connection is re-established, until the
        # projector is turned back on via the remote.
        # hence power off sleeps for 10 seconds while holding the send lock.
        (state, delay) = ('ON', 0) if on_off else ('OFF', 10)
        await self._execute_command(COMMAND.POWER, state, delay=delay)

    async def set_source(self, source_name):
        for code, name in self._sources_dict.items():
            if name == source_name:
                await self._execute_command(COMMAND.SOURCE, code)
                return
        LOG.warning("Unknown source name: " + source_name)

    def log_state(self):
        LOG.debug("Serial number: " + repr(self.serial_number))
        LOG.debug("Power status: " + _power_status_str(self._power_status))
        LOG.debug("Connection status: " + repr(self.connection_ok))
        LOG.debug("Source list: " + repr(self.source_list))
        LOG.debug("Source: " + repr(self.source))

    async def _connect(self):
        LOG.debug('Connecting to %s:%d...' % (self._host, self._port))
        connection_factory = lambda: Connection(
                self._on_imevent, self._on_disconnect)
        transport, connection = await asyncio.wait_for(
                asyncio.get_running_loop().create_connection(
                    connection_factory, host=self._host, port=self._port),
                timeout=30)
        await connection.handshake()
        self._connection = connection
        await self._update_status()
        LOG.debug("Connection success!")

    async def _monitor_connection(self):
        while True:
            try:
                await asyncio.sleep(30)
                await self._monitor_connection_once()
            except asyncio.exceptions.CancelledError:
                raise
            except:
                logging.exception("Connection monitor exception")

    async def _monitor_connection_once(self):
        if con := self._connection:
            age = con.last_response_age()
            if age > timedelta(minutes=1): await con.send_command('')
            if age > timedelta(minutes=3):
                LOG.warning("Communication timeout: resetting connection.")
                self._connection.close()
        else:
            try: await self._connect()
            except asyncio.exceptions.TimeoutError as e:
                LOG.debug("Connection timed out...")

    async def _query(self, command):
        if not self.connection_ok: raise RuntimeError("Connection not ready")
        resp = await self._connection.send_command(command + '?')
        if not resp.startswith(command + '='):
            raise RuntimeError("Malformed query response: " + resp)
        return resp[len(command)+1:]

    async def _execute_command(self, command, arg, delay=0):
        if not self.connection_ok: raise RuntimeError("Connection not ready")
        await self._connection.send_command(command + ' ' + arg, delay=delay)

    async def _update_status(self):
        if not self._power_status:
            self._power_status = int(await self._query(COMMAND.POWER))
        if not self.serial_number:
            self.serial_number = await self._query(COMMAND.SERIAL_NUMBER)

        if not self.power: return
        try:
            self._source = await self._query(COMMAND.SOURCE)
            if not len(self._sources_dict):
                sl = (await self._query(COMMAND.SOURCE_LIST)).split(' ')
                self._sources_dict = { code:name for code,name in zip(sl[0::2], sl[1::2]) }
        except asyncio.exceptions.CancelledError: raise
        except: LOG.debug("Not ready to retrieve sources.")

    def _on_imevent(self, data):
        self._power_status = EVENT_TO_POWER_STATUS[int(data.split(' ')[1])]
        asyncio.ensure_future(self._update_status())

    def _on_disconnect(self):
        self._connection = None
        self._power_state = None
        self._source = None

