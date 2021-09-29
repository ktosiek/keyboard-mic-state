import io
import os
import time
from datetime import datetime, timedelta
from typing import Tuple, Optional, Generic, TypeVar

import pulsectl

MIC_MUTE_KEY = 3  # prog
MIC_ACTIVE_LED_MODE = 0  # domyślny, pusty tryb


def main():
    pulse = pulsectl.Pulse()
    with FocusTty('/dev/ttyACM0') as tty:
        focus = FocusClient(tty)
        prev_mode: Cell[Optional[int]] = Cell(None)
        try:
            focus.reset()
            main_loop(focus, prev_mode, pulse)
        finally:
            restore(focus, prev_mode.get())


def main_loop(focus, prev_mode, pulse):
    prev_sink_open = False
    while True:
        sink_open = any(m for m in pulse.source_list() if m.state == pulsectl.PulseStateEnum.running and not m.mute)
        if sink_open and not prev_sink_open:
            print('sink opened')
            prev_mode.set(focus.get_led_mode())
            focus.set_led_mode(MIC_ACTIVE_LED_MODE)
            focus.set_led_at(MIC_MUTE_KEY, (250, 0, 0))

        if not sink_open and prev_sink_open:
            print('sink closed')
            restore(focus, prev_mode.get())
            prev_mode.set(None)

        prev_sink_open = sink_open
        time.sleep(0.1)


def restore(focus: 'FocusClient', prev_mode: 'Optional[int]'):
    if prev_mode is not None:
        focus.set_led_mode(prev_mode)


class FocusClient:
    def __init__(self, tty: 'FocusTty'):
        self._tty = tty

    def reset(self):
        self._tty.read()
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
        self._tty.read()  # Upewnij się że nic nie wisi w buforze
        self._tty.writeline(command)
        return list(self._read_result())

    def _read_result(self):
        deadline = datetime.now() + timedelta(seconds=5)
        while datetime.now() < deadline:
            line = self._tty.readline()
            if not line:
                time.sleep(0.1)
            elif line == b'.':
                return
            else:
                yield line
        raise ProtocolError("""Timed out while waiting for ".".""")


class FocusTty:
    _tty: Optional[io.FileIO]

    def __init__(self, path):
        self._debug = True
        self._path = path
        self._tty = None

    def __enter__(self):
        assert self._tty is None
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        self._tty = io.FileIO(os.open(self._path, os.O_RDWR | os.O_NOCTTY), "r+b")

    def close(self):
        self._tty.close()

    def writeline(self, line: bytes) -> None:
        line = line + b'\n'
        if self._debug:
            print('write', line)
        self._tty.write(line + b'\n')
        self._tty.flush()

    def readline(self) -> bytes:
        line = self._tty.readline().removesuffix(b'\r\n')
        if self._debug:
            print('read', line)
        return line

    def read(self):
        return self._tty.read()


T = TypeVar('T')


class Cell(Generic[T]):
    def __init__(self, value: T):
        self._value = T

    def get(self) -> T:
        return self._value

    def set(self, value: T):
        self._value = value


class ProtocolError(Exception):
    pass


if __name__ == '__main__':
    main()
