import asyncio
import sys

from pyiwctl.config import PyIwctlNetworkConfig
from pyiwctl.iwctl import Iwctl

loop = asyncio.get_event_loop()


async def be_connected(iwctl):
    await iwctl.main_init()
    phy0 = list(iwctl.adapters.values())[0]
    wlan0 = list(phy0.devices.values())[0]

    print("my device:", wlan0.name)
    while True:
        if wlan0.state == 'disconnected':
            print("Go scanning !")
            await wlan0.scan(wait_result=True)
            for net in wlan0.networks:
                if iwctl.is_known_network(net):
                    print("Connect result:", await wlan0.connect(net, wait_result=True))
        else:
            print("My state is:", wlan0.state)
            await wlan0.wait_state_event()


nets_config = [
    PyIwctlNetworkConfig("MyBoxSSID", "MyBoxPSK"),
    PyIwctlNetworkConfig("OtherBoxSSID", "OtherBoxPSK"),
]

iwctl = Iwctl(loop, nets_config)
loop.run_until_complete(be_connected(iwctl))

loop.run_forever()
sys.exit(0)
