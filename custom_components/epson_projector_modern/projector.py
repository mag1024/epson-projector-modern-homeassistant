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

class CommandError(Exception):
    pass

class Connection(asyncio.Protocol):
    ESCVPNET = 'ESC/VP.net'
    IMEVENT = 'IMEVENT'
    SEND_TERMINATOR = '\r\n'
    RECV_TERMINATOR = '\r:'

    def __init__(self, on_imevent, on_disconnect):
        self._on_imevent = on_imevent
        self._on_disconnect = on_disconnect
        self._transport = None
        self._pending = asyncio.Queue()
        self._buffer = ""
        self._response_event = asyncio.Event()
        self._last_response = None

    def connection_made(self, transport):
        self._transport = transport

    def connection_lost(self, exc):
        LOG.info("Connection terminated.")
        while self._pending.qsize():
            (cmd, fut) = self._pending.get_nowait()
            fut.set_exception(CommandError())
        self._buffer = ""
        self._on_disconnect()

    def data_received(self, data):
        LOG.debug("<< %s", data)
        self._last_response = datetime.now()
        self._buffer += data.decode()
        self._try_consume_buffer()

    def send_command(self, command, arg, terminator = SEND_TERMINATOR) -> asyncio.Future:
        response = asyncio.get_running_loop().create_future()
        self._pending.put_nowait((command, response))
        self.send_command_no_response(command + arg, terminator)
        return response

    def send_command_no_response(self, command, terminator = SEND_TERMINATOR):
        request = (command + terminator).encode('ascii')
        LOG.debug(">> %s", request)
        self._transport.write(request)

    async def handshake(self):
        resp = await self.send_command(self.ESCVPNET, '', '\x10\x03\x00\x00\x00\x00')
        status = ord(resp[14])
        if status != STATUS_OK: raise RuntimeError("Handshake error: " + STATUS[status])

    async def wait_ready(self):
        if self._response_event.is_set(): self._response_event.clear()
        for i in range(0, 6):
            if self._response_event.is_set(): return
            self.send_command_no_response('')
            try:
                await asyncio.wait_for(self._response_event.wait(), timeout=5)
            except asyncio.exceptions.TimeoutError as e:
                LOG.debug("...")
        LOG.warning("Waiting for ready timed out; resetting connection.")
        self.close()

    def close(self):
        if self._transport:
            self._transport.abort()
            self._transport = None

    def last_response_age(self):
        return datetime.now() - self._last_response

    def _try_consume_buffer(self):
        while self._buffer.startswith(':'):
            self._response_event.set()
            self._buffer = self._buffer[1:]

        if self._buffer.startswith(self.IMEVENT):
            (resp, self._buffer) = self._try_consume_buffer_to_terminator()
            if resp: self._on_imevent(resp[len(self.IMEVENT) + 1:])
            return

        if self._buffer.startswith(self.ESCVPNET):
            if len(self._buffer) < 16: return
            # insert a terminator so it can be processed like a regular command
            self._buffer = self._buffer[0:16] + self.RECV_TERMINATOR + self._buffer[16:]

        (resp, self._buffer) = self._try_consume_buffer_to_terminator()
        if not resp: return

        (cmd, fut) = self._pending.get_nowait()
        if resp == 'ERR':
            fut.set_exception(CommandError())
            return
        while not resp.startswith(cmd):
            LOG.warning("Command mismatch: expected %s, got %s" % (cmd, resp))
            fut.set_exception(CommandError())
            if not self._pending.qsize(): return
            (cmd, fut) = self._pending.get_nowait()
        fut.set_result(resp)

    def _try_consume_buffer_to_terminator(self) -> (str, str):
        end = self._buffer.find(self.RECV_TERMINATOR)
        if end < 0: return (None, self._buffer)
        return self._buffer[0:end], self._buffer[end+len(self.RECV_TERMINATOR):]


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
    def power(self) -> bool: return self._power_status and self._power_status in [1, 2]
    @property
    def connection_ok(self) -> bool: return self._connection != None
    @property
    def source_list(self) -> [str]: return list(self._sources_dict.values())
    @property
    def source(self) -> str:
        try:
            return self._sources_dict[self._source]
        except:
            return 'unknown'

    async def set_power(self, on_off):
        await self._execute_command(COMMAND.POWER, "ON" if on_off else "OFF")
        await self._connection.wait_ready()

    async def set_source(self, source_name):
        for code, name in self._sources_dict.items():
            if name == source_name:
                await self._execute_command(COMMAND.SOURCE, code)
                return
        LOG.warning("Unknown source name: " + source_name)

    def log_state(self):
        LOG.debug("Serial number: " + self.serial_number)
        LOG.debug("Power status: " + POWER_STATUS[self._power_status])
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
        if self._connection:
            age = self._connection.last_response_age()
            if age > timedelta(minutes=1): self._keepalive()
            if age > timedelta(minutes=3):
                LOG.warning("Communication timeout: resetting connection.")
                self._connection.close()
        else:
            try:
                await self._connect()
            except asyncio.exceptions.TimeoutError as e:
                LOG.debug("Connection timed out...")

    async def _query(self, command):
        if not self.connection_ok: raise RuntimeError("Connection not ready")
        resp = await self._connection.send_command(command, '?')
        if not resp.startswith(command + '='):
            raise RuntimeError("Malformed query response: " + resp)
        return resp[len(command)+1:]

    async def _execute_command(self, command, arg):
        if not self.connection_ok: raise RuntimeError("Connection not ready")
        self._connection.send_command_no_response(command + ' ' + arg)
        await self._connection.wait_ready()

    def _keepalive(self):
        self._connection.send_command_no_response('')

    async def _update_status(self):
        await self._connection.wait_ready()
        self._power_status = int(await self._query(COMMAND.POWER))
        if not self.serial_number:
            self.serial_number = await self._query(COMMAND.SERIAL_NUMBER)
        try:
            self._source = await self._query(COMMAND.SOURCE)
            if not len(self._sources_dict):
                sl = (await self._query(COMMAND.SOURCE_LIST)).split(' ')
                self._sources_dict = { code:name for code,name in zip(sl[0::2], sl[1::2]) }
        except asyncio.exceptions.CancelledError:
            raise
        except:
            LOG.debug("Not ready to retrieve sources.")

    def _on_imevent(self, data):
        LOG.debug("Status update: " + data)
        asyncio.ensure_future(self._update_status())

    def _on_disconnect(self):
        self._connection = None

