#
#     PyIwctl - Python dbus client for iwd
#     Copyright (C) 2020-2021 Inemajo
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import asyncio
import logging
from dataclasses import dataclass
from dbus_next import BusType
from dbus_next import DBusError
from dbus_next import Variant
from dbus_next.aio import MessageBus
from dbus_next.errors import DBusError
from dbus_next.service import ServiceInterface
from dbus_next.service import dbus_property
from dbus_next.service import method
from dbus_next.service import signal

from .config import PyIwctlAdapter
from .config import PyIwctlDevice
from .config import PyIwctlStatus

LOGGER = logging.getLogger('iwctl.iwctl')


class MyIwdAgent(ServiceInterface):
    def __init__(self, iwctl):
        super().__init__('net.connman.iwd.Agent')
        self._iwctl = iwctl

    @method()
    def Release(self):
        LOGGER.warning("Operation Release")

    @method()
    def RequestPassphrase(self, network: 'o') -> 's':
        net = self._iwctl._get_network_from_dbus_path(network)
        if net is None:
            raise DBusError('net.connman.iwd.Agent.Error.Canceled', 'Unknown this network')
        LOGGER.debug("Found network: %s", net.name)

        net_config = self._iwctl.get_network_config_from_net(net)
        if net_config is None:
            raise DBusError('net.connman.iwd.Agent.Error.Canceled', 'Unknown psk for this net')

        return net_config.psk

    @method()
    def RequestPrivateKeyPassphrase(self, network: 'o') -> 's':
        raise DBusError('net.connman.iwd.Agent.Error.Canceled',
                        'NotImplemented: RequestPrivateKeyPassphrase')

    @method()
    def RequestUserNameAndPassword(self, network: 'o') -> 'ss':
        raise DBusError('net.connman.iwd.Agent.Error.Canceled',
                        'NotImplemented: RequestUserNameAndPassword')

    @method()
    def RequestUserPassword(self, network: 'o', user: 's') -> 's':
        raise DBusError('net.connman.iwd.Agent.Error.Canceled',
                        'NotImplemented: RequestUserPassword')

    @method()
    def Cancel(self, reason: 's'):
        return 'Operation Canceled'


@dataclass
class MyPyIwctlDevice(PyIwctlDevice):
    _iwctl: str = None

    async def _call_scan(self):
        bus = self._iwctl.bus
        introspection = await bus.introspect('net.connman.iwd', self._dbus_path)
        device_obj = bus.get_proxy_object('net.connman.iwd', self._dbus_path, introspection)
        device = device_obj.get_interface('net.connman.iwd.Station')
        loop = asyncio.get_event_loop()
        self._scan_result_terminate = loop.create_future()

        try:
            await device.call_scan()
        except DBusError as e:
            if e.type == 'net.connman.iwd.InProgress':
                LOGGER.debug(f" >>>> self.state {self.state}  <<<< self.state")
            else:
                raise e

    async def scan(self, wait_result=False):
        if self._scan_result_terminate is None:
            await self._call_scan()
        if wait_result is True and self._scan_result_terminate is not None:
            await self._scan_result_terminate

    @classmethod
    def from_dbus(cls, path, d, iwctl):
        obj = super().from_dbus(path, d)
        obj._iwctl = iwctl
        return obj

    async def wait_state_event(self):
        if self._state_changed_future is None:
            loop = asyncio.get_event_loop()
            self._state_changed_future = loop.create_future()

        await self._state_changed_future

    async def _call_connect(self, net):
        loop = asyncio.get_event_loop()
        self._try_connect_finished = loop.create_future()

        bus = self._iwctl.bus
        introspection = await bus.introspect('net.connman.iwd', net._dbus_path)
        net_obj = bus.get_proxy_object('net.connman.iwd', net._dbus_path, introspection)
        net = net_obj.get_interface('net.connman.iwd.Network')

        tries = 5
        for _ in range(tries):
            try:
                await net.call_connect()
            except DBusError as e:
                if e.type == 'net.connman.iwd.Aborted':
                    continue
                else:
                    raise e
            break
        else:
            raise Exception("Too many connect tries")

    async def connect(self, wanted_net, wait_result=False):
        for net in self.networks:
            if net.name == wanted_net.name:
                break
        else:
            raise Exception(f"Not found {wanted_net}")

        if self._try_connect_finished is None:
            await self._call_connect(net)

        if wait_result is True and self._try_connect_finished is not None:
            await self._try_connect_finished

        return self.state


class Iwctl(PyIwctlStatus):
    def __init__(self, loop, nets_config):
        super().__init__()
        self.nets_config = nets_config
        self._agent = MyIwdAgent(self)
        self.bus = None
        self.wlan0_id = None
        self._loop = loop
        self._changed_notify_ifaces = {}

    def changed_notify_interface(self, action, path, value):
        self._network_changed(action, path, value)

    def changed_notify(self, path, a: 's', b: 'a{sv}', c: 'as'):
        device = self._get_device_by_path(path)
        device._station_changed(path, b)

    def _get_iwctl_object(self, dbus_path, object_type, object_kwargs):
        try:
            obj = {
                'net.connman.iwd.Device': MyPyIwctlDevice,
            }[object_type]
        except KeyError:
            return super()._get_iwctl_object(dbus_path, object_type, object_kwargs)

        return obj.from_dbus(dbus_path, object_kwargs, self)

    async def main_init(self):
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        await self.resync_objects()
        await self.install_agent()

        introspection = await self.bus.introspect('net.connman.iwd', '/')
        obj = self.bus.get_proxy_object('net.connman.iwd', '/', introspection)
        manager = obj.get_interface('org.freedesktop.DBus.ObjectManager')
        manager.on_interfaces_added(
            lambda path, value: self.changed_notify_interface('add', path, value)
        )
        manager.on_interfaces_removed(
            lambda path, value: self.changed_notify_interface('del', path, value)
        )

    async def resync_objects(self):
        introspection = await self.bus.introspect('net.connman.iwd', '/')
        obj = self.bus.get_proxy_object('net.connman.iwd', '/', introspection)
        manager = obj.get_interface('org.freedesktop.DBus.ObjectManager')
        result = await manager.call_get_managed_objects()
        self._dbus_update(result)

        for adapter in self.adapters.values():
            for iface in adapter.devices.values():
                if iface._dbus_path not in self._changed_notify_ifaces:
                    introspection = await self.bus.introspect('net.connman.iwd', iface._dbus_path)
                    obj = self.bus.get_proxy_object('net.connman.iwd',
                                                    iface._dbus_path,
                                                    introspection)
                    manager = obj.get_interface('org.freedesktop.DBus.Properties')
                    manager.on_properties_changed(
                        lambda x, y, z: self.changed_notify(iface._dbus_path, x, y, z))
                    self._changed_notify_ifaces[iface._dbus_path] = True

    async def install_agent(self):
        introspection = await self.bus.introspect('net.connman.iwd', '/net/connman/iwd')
        device_obj = self.bus.get_proxy_object('net.connman.iwd', '/net/connman/iwd', introspection)
        device = device_obj.get_interface('net.connman.iwd.AgentManager')

        self.bus.export('/com/example/sample0', self._agent)
        await device.call_register_agent('/com/example/sample0')

    def get_network_config_from_net(self, net):
        for net_config in self.nets_config:
            if net_config.ssid == net.name:
                return net_config

    def is_known_network(self, net):
        if net.name in self.known_networks:
            return True
        return self.get_network_config_from_net(net) is not None
