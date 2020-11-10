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

from typing import Dict
from typing import List

import logging
from dataclasses import dataclass

LOGGER = logging.getLogger('iwctl.config')


@dataclass
class PyIwctlNetworkConfig:
    ssid: str
    psk: str = None

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class PyIwctlKnownNetworkAuth:
    # Virtual class
    type: str


@dataclass
class PyIwctlKnownNetworkAuthPassphare(PyIwctlKnownNetworkAuth):
    psk: str
    type = 'psk'


@dataclass
class PyIwctlKnownNetwork:
    auth_conf: PyIwctlKnownNetworkAuth
    auth_type: str
    name: str
    hidden: bool
    auto_connect: bool
    last_connected_time: str
    _dbus_path: str = None

    AUTH_TYPE_TO_CONF = {
        "psk": PyIwctlKnownNetworkAuthPassphare,
    }

    @classmethod
    def from_dict(cls, d):
        auth_cls = cls.AUTH_TYPE_TO_CONF[d['auth_type']]
        auth_kwargs = d['auth_conf']
        auth = auth_cls(**auth_kwargs)

        ssid = d['ssid']

        return cls(ssid=ssid, auth=auth)

    @classmethod
    def from_dbus(cls, path, d):
        return cls(
            name=d['Name'].value,
            auth_type=d['Type'].value,
            auth_conf=None,
            hidden=d['Hidden'].value,
            auto_connect=d['AutoConnect'].value,
            last_connected_time=d['LastConnectedTime'].value,
            _dbus_path=path,
        )


@dataclass
class PyIwctlNetwork:
    name: str
    connected: bool
    device: str
    auth_type: str
    _dbus_path: str = None

    @classmethod
    def from_dbus(cls, path, d):
        return cls(
            name=d['Name'].value,
            connected=d['Connected'].value,
            device=d['Device'].value,
            auth_type=d['Type'].value,
            _dbus_path=path,
        )


@dataclass
class PyIwctlDevice:
    name: str
    address: str
    powered: bool
    adapter: str
    mode: str
    networks: List[PyIwctlNetwork] = None
    _dbus_path: str = None

    def __post_init__(self):
        self._scan_result_terminate = None
        self._state_changed_future = None
        self._try_connect_finished = None
        self.state = None

    @classmethod
    def from_dbus(cls, path, d):
        return cls(
            name=d['Name'].value,
            address=d['Address'].value,
            powered=d['Powered'].value,
            adapter=d['Adapter'].value,
            mode=d['Mode'].value,
            networks=[],
            _dbus_path=path,
        )

    def add_network(self, network):
        self.networks.append(network)

    def _get_network_from_dbus_path(self, dbus_path):
        for net in self.networks:
            if net._dbus_path == dbus_path:
                return net

    def del_network_from_dbus_path(self, dbus_path):
        for net in self.networks:
            if net._dbus_path == dbus_path:
                break
        else:
            raise Exception(f"not found {dbus_path}")
        self.networks.remove(net)

    def _station_changed(self, dbus_path, object_kwargs):
        if 'Scanning' in object_kwargs:
            if object_kwargs['Scanning'].value is False:
                if self._scan_result_terminate is not None:
                    self._scan_result_terminate.set_result(None)
                    self._scan_result_terminate = None

        if 'State' in object_kwargs:
            self.state = object_kwargs['State'].value
            if self._state_changed_future is not None:
                self._state_changed_future.set_result(True)
                self._state_changed_future = None

            if self.state in ('connected', 'disconnected'):
                if self._try_connect_finished is not None:
                    self._try_connect_finished.set_result(self.state)
                    self._try_connect_finished = None

    def is_connected(self):
        return self.state == 'connected'


@dataclass
class PyIwctlAdapter:
    powered: bool
    model: str
    vendor: str
    name: str
    supported_modes: List[str]
    devices: Dict[str, PyIwctlDevice]
    _dbus_path: str = None

    @classmethod
    def from_dbus(cls, path, d):
        return cls(
            powered=d['Powered'].value,
            model=d['Model'].value,
            vendor=d['Vendor'].value,
            name=d['Name'].value,
            supported_modes=d['SupportedModes'].value,
            devices={},
            _dbus_path=path,
        )

    def add_device(self, device):
        self.devices[device._dbus_path] = device

    def _get_device_by_path(self, dbus_path):
        assert(dbus_path.startswith(self._dbus_path))

        # strip() path and get only the adapter part
        dbus_path = '/'.join(dbus_path.split("/")[0:6])
        try:
            return self.devices[dbus_path]
        except KeyError as exc:
            raise FileNotFoundError(dbus_path) from exc


@dataclass
class PyIwctlStatus:
    known_networks: Dict[str, PyIwctlKnownNetwork] = None
    adapters: Dict[str, PyIwctlAdapter] = None

    def __post_init__(self):
        if self.adapters is None:
            self.adapters = {}

        if self.known_networks is None:
            self.known_networks = {}

    def add_adapter(self, adapter):
        self.adapters[adapter._dbus_path] = adapter

    def _get_network_from_dbus_path(self, dbus_path):
        device = self._get_device_by_path(dbus_path)
        return device._get_network_from_dbus_path(dbus_path)

    def _get_device_by_path(self, dbus_path):
        adapter = self._get_adapter_by_path(dbus_path)
        return adapter._get_device_by_path(dbus_path)

    def _get_adapter_by_path(self, dbus_path):
        assert(dbus_path.startswith("/net/connman/iwd/"))

        # strip() path and get only the adapter part
        dbus_path = '/'.join(dbus_path.split("/")[0:5])
        try:
            return self.adapters[dbus_path]
        except KeyError as exc:
            raise FileNotFoundError(dbus_path) from exc

    def add_known_network(self, known_network):
        self.known_networks[known_network.name] = known_network

    def _get_iwctl_object(self, dbus_path, object_type, object_kwargs):
        try:
            cls = {
                'net.connman.iwd.Adapter': PyIwctlAdapter,
                'net.connman.iwd.Device': PyIwctlDevice,
                'net.connman.iwd.Network': PyIwctlNetwork,
                'net.connman.iwd.KnownNetwork': PyIwctlKnownNetwork,
            }[object_type]
        except KeyError:
            return None

        return cls.from_dbus(dbus_path, object_kwargs)

    def _dbus_update(self, entries):
        self.adapters = {}
        self.known_networks = {}

        for dbus_path, dbus_dict in entries.items():
            for object_type, object_kwargs in dbus_dict.items():
                obj = self._get_iwctl_object(dbus_path, object_type, object_kwargs)
                if object_type == 'net.connman.iwd.Adapter':
                    self.add_adapter(obj)
                elif object_type == 'net.connman.iwd.Device':
                    adapter = self._get_adapter_by_path(dbus_path)
                    adapter.add_device(obj)
                elif object_type == 'net.connman.iwd.Network':
                    device = self._get_device_by_path(dbus_path)
                    device.add_network(obj)
                elif object_type == 'net.connman.iwd.KnownNetwork':
                    self.add_known_network(obj)
                elif object_type == 'net.connman.iwd.Station':
                    device = self._get_device_by_path(dbus_path)
                    device._station_changed(dbus_path, object_kwargs)
                else:
                    LOGGER.info("Unkown object: %s %s", object_type, object_kwargs)

    def _network_changed(self, action, dbus_path, objects):
        if 'net.connman.iwd.Network' in objects:
            device = self._get_device_by_path(dbus_path)
            if action == 'add':
                net = PyIwctlNetwork.from_dbus(dbus_path,
                                               objects['net.connman.iwd.Network'])
                device.add_network(net)
            elif action == 'del':
                device.del_network_from_dbus_path(dbus_path)
