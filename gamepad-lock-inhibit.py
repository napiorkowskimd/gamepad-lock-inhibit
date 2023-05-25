#!/bin/env python3
import asyncio
import os
import logging
from functools import partial
from typing import Dict, Optional

import dbus
import evdev
import pyudev


class GamepadsFinder:
    SUBSYSTEM = 'input'
    SYS_NAME_PREFIX = 'event'

    def __init__(self, loop: asyncio.AbstractEventLoop, cb_add, cb_remove):
        self.logger = logging.getLogger("GamepadsFinder")

        self.context = pyudev.Context()
        self.devices = list(GamepadsFinder.get_device_path(x) for x in self.context.list_devices(
            subsystem=self.SUBSYSTEM, ID_INPUT_JOYSTICK=1, sys_name=self.SYS_NAME_PREFIX+"*"))
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem=self.SUBSYSTEM)
        self.observer = pyudev.MonitorObserver(
            self.monitor, callback=self._on_new_event, name='monitor-observer')
        self.loop = loop
        self.cb_add = cb_add
        self.cb_remove = cb_remove

    @staticmethod
    def get_device_path(device):
        return device.device_node

    def start(self):
        self.logger.info("Start monitoring udev for gamepad devices")
        self.observer.start()

    def stop(self):
        self.logger.info("Stop monitoring udev for gamepad devices")
        self.observer.stop()

    def _on_new_event(self, device: pyudev.Device):
        if device.action not in ('add', 'remove'):
            return

        try:
            if not device.properties.asbool('ID_INPUT_JOYSTICK'):
                return
        except KeyError:
            return
        if not device.sys_name.startswith(self.SYS_NAME_PREFIX):
            return

        self.logger.info(f"{device} action {device.action}")

        if device.action == 'add':
            self.loop.call_soon_threadsafe(
                self.cb_add, GamepadsFinder.get_device_path(device))
        else:
            self.loop.call_soon_threadsafe(
                self.cb_remove, GamepadsFinder.get_device_path(device))


class GamepadsWatcher:
    def __init__(self):
        self.logger = logging.getLogger("GamepadsWatcher")
        self.gamepad_active = False
        self.started = False
        self.tasks: Dict[str, asyncio.Task] = {}
        self.devices: Dict[str, evdev.InputDevice] = {}

    def set_init_devices(self, devices):
        for device in devices:
            self.tasks[device] = None

    def create_monitor_task(self, device):
        gamepad = evdev.InputDevice(device)
        self.devices[device] = gamepad
        self.tasks[device] = asyncio.create_task(
            self.monitor_gamepad_events(gamepad))
        self.tasks[device].add_done_callback(
            partial(self.finish_removing_device, device))

    def add_device(self, device):
        self.logger.info(f"Adding device {device}")
        task = self.tasks.get(device, None)
        if task is not None:
            self.logger.warning(f"device {device} is already present")
            return

        if not self.started:
            self.tasks[device] = None
            return

        self.create_monitor_task(device)

    def remove_device(self, device):
        self.logger.info(f"Removing device {device}")
        task = self.tasks.get(device, None)
        if task is None:
            try:
                del self.tasks[device]
            except KeyError:
                pass
            return
        task.cancel()
        self.devices[device].close()
        del self.devices[device]

    def finish_removing_device(self, device, future):
        del self.tasks[device]

    def start(self):
        self.started = True
        devices = list(self.tasks.keys())
        for device in devices:
            self.logger.info(f"create monitor for {device}")
            self.create_monitor_task(device)

    async def stop(self):
        self.started = False
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks)

    async def monitor_gamepad_events(self, device: evdev.InputDevice):
        self.logger.info(f"monitor for {device.name} starts")
        try:
            while True:
                async for _ in device.async_read_loop():
                    self.gamepad_active = True
        except (asyncio.CancelledError):
            self.logger.info(f"monitor for {device.name} exits")
        except OSError as err:
            if err.errno == 19:
                self.logger.info(f"{device.name} disconnected, exit monitor")
            else:
                self.logger.error(f"{device} monitor failed with error {err}")

    def get_and_reset_active(self):
        active = self.gamepad_active
        self.gamepad_active = False
        return active


class IdleLock:
    def __init__(self):
        self.logger = logging.getLogger("IdleLock")
        self.fd: Optional[dbus.UnixFd] = None
        self.bus = dbus.SystemBus()
        self.logind = self.bus.get_object('org.freedesktop.login1',
                                          '/org/freedesktop/login1')
        self.iface = dbus.Interface(
            self.logind, dbus_interface='org.freedesktop.login1.Manager')

    def lock_idle(self):
        if self.fd is not None:
            return
        self.logger.info("Inhibiting idle")
        self.fd = self.iface.Inhibit(
            "shutdown:idle", "Gamepad Idle Inhibit", "Gamepad active", "block")

    def unlock_idle(self):
        if self.fd is None:
            return
        self.logger.info("Releasing idle lock")
        os.close(self.fd.take())
        self.fd = None


async def inhibit_idle_when_gamepads_active(watcher: GamepadsWatcher, interval: float):
    lock = IdleLock()
    try:
        while True:
            await asyncio.sleep(interval)
            active = watcher.get_and_reset_active()
            if active:
                lock.lock_idle()
            else:
                lock.unlock_idle()
    except asyncio.CancelledError:
        logging.info(f"Inhibit task exits")
        lock.unlock_idle()
        raise


async def main():
    logging.basicConfig(level=logging.INFO)
    watcher = GamepadsWatcher()
    finder = GamepadsFinder(asyncio.get_event_loop(),
                            watcher.add_device, watcher.remove_device)
    watcher.set_init_devices(finder.devices)
    inhibit_task = asyncio.create_task(
        inhibit_idle_when_gamepads_active(watcher, 30.0))
    try:
        logging.info(f"Start watchers")
        finder.start()
        watcher.start()
        await inhibit_task
    except asyncio.CancelledError:
        logging.info(f"Stop watchers")
        finder.stop()
        await watcher.stop()
        inhibit_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Exiting...")
