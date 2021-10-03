import asyncio
import fcntl
import io
import logging
import os
import select
import time
from typing import Tuple, Optional, Generic, TypeVar, List, Generator, AsyncGenerator, Iterable

import pulsectl_asyncio
from pulsectl import PulseSourceInfo, PulseStateEnum, PulseEventMaskEnum

logger = logging.getLogger('main')

MIC_MUTE_KEY = 3  # prog
MIC_ACTIVE_LED_MODE = 0  # domyślny, pusty tryb

DEBUG = os.environ.get('MIC_STATE_DEBUG', '').lower() in ('1', 't', 'true')

CLIENT_NAME = "keyboard-mic-state"


async def generate_pulse_sources() -> AsyncGenerator[List[PulseSourceInfo], None]:
    async with pulsectl_asyncio.PulseAsync(CLIENT_NAME) as pulse:
        yield await pulse.source_list()
        async for event in pulse.subscribe_events(
                PulseEventMaskEnum.source_output,
                PulseEventMaskEnum.source,
        ):
            logger.debug("got PA event: %r", event)
            yield await pulse.source_list()


async def main():
    with FocusTty('/dev/ttyACM0') as tty:
        focus = FocusClient(tty)
        pulse_sources_stream = generate_pulse_sources()
        prev_mode: Cell[Optional[int]] = Cell(None)
        try:
            focus.reset()
            await main_loop(focus, prev_mode, pulse_sources_stream)
        finally:
            logger.info('exit')
            restore(focus, prev_mode.get())


async def main_loop(focus, prev_mode, pulse_sources_stream: AsyncGenerator[List[PulseSourceInfo], None]):
    prev_sink_open = False
    async for source_list in pulse_sources_stream:
        # noinspection PyUnresolvedReferences
        sink_open = any(m.state == PulseStateEnum.running and not m.mute for m in source_list)
        if sink_open and not prev_sink_open:
            on_source_change(focus, prev_mode, sink_open)

        if not sink_open and prev_sink_open:
            on_source_change(focus, prev_mode, sink_open)

        prev_sink_open = sink_open
        time.sleep(0.1)


def on_source_change(focus: 'FocusClient', prev_mode: 'Cell[Optional[int]]', source_open: bool):
    if source_open:
        logger.info('source opened')
        prev_mode.set(focus.get_led_mode())
        focus.set_led_mode(MIC_ACTIVE_LED_MODE)
        focus.set_led_at(MIC_MUTE_KEY, (250, 0, 0))
    else:
        logger.info('source closed')
        restore(focus, prev_mode.get())
        prev_mode.set(None)


def restore(focus: 'FocusClient', prev_mode: 'Optional[int]'):
    logger.info("restore")
    if prev_mode is not None:
        focus.set_led_mode(prev_mode)


class FocusClient:
    def __init__(self, tty: 'FocusTty'):
        self._tty = tty

    def reset(self):
        self._tty.discard_pending_data()
        self.run_command(b'')

    def get_led_mode(self) -> int:
        response = self.run_command(b'led.mode')
        mode, = response
        return int(mode.strip())

    def set_led_mode(self, mode_id: int):
        self.run_command('led.mode {}'.format(mode_id).encode('ascii'))

    def set_led_at(self, index: int, rgb: Tuple[int, int, int]):
        self.run_command('led.at {} {} {} {}'.format(index, *rgb).encode('ascii'))

    def run_command(self, command: bytes):
        self._tty.writeline(command)
        return list(self._read_result())

    def _read_result(self):
        for line in self._tty.readlines():
            if line == b'.':
                return
            elif line:
                yield line


class FocusTty:
    _tty: Optional[io.FileIO]

    def __init__(self, path):
        self._path = path
        self._tty = None

    def __enter__(self):
        assert self._tty is None
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        fd = os.open(self._path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, TIOCEXCL)
            self._tty = io.FileIO(fd, "r+b")
        except:  # noqa
            os.close(fd)

    def close(self):
        self._tty.close()

    def writeline(self, line: bytes) -> None:
        line = line + b'\n'
        logger.debug('write: %r', line)
        self.write_all(line)
        self._tty.flush()

    def readlines(self) -> Generator[bytes, None, None]:
        chunks = readchunks(self._tty)
        for line in splitter(chunks, b'\n'):
            yield line.removesuffix(b'\r')

    def write_all(self, buff: bytes):
        while (written := self._tty.write(buff)) != len(buff):
            buff = buff[written:]
            logger.debug("partial write, %s bytes left", len(buff))
            select.select([], [self._tty.fileno()], [])

    def discard_pending_data(self):
        data = self._tty.read()
        if data:
            logger.warning('unexpected data when starting: %r', data)


def readchunks(f: io.FileIO) -> Generator[bytes, None, None]:
    while True:
        new_data = f.read()
        logger.debug('read: %r', new_data)
        if new_data:
            yield new_data
        logger.debug('waiting for more data')
        select.select([f.fileno()], [], [])


def splitter(chunks: Iterable[bytes], separator: bytes) -> Generator[bytes, None, None]:
    buff = b''
    for chunk in chunks:
        buff += chunk
        *results, buff = buff.split(separator)
        yield from results
    yield buff


TIOCEXCL = 0x540C

T = TypeVar('T')


class Cell(Generic[T]):
    def __init__(self, value: T):
        self._value = value

    def get(self) -> T:
        return self._value

    def set(self, value: T):
        self._value = value


class EmptyReadException(Exception):
    pass


if __name__ == '__main__':
    try:
        logging.basicConfig(
            format='%(asctime)-15s %(levelname)s %(message)s',
            level=logging.DEBUG if DEBUG else logging.INFO,
        )
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
