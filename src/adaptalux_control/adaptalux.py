"""Bluetooth constants for the Adaptalux Control Pod 3.0.

The pod's Bluetooth module exposes a Microchip "Transparent UART" service: a byte
pipe. Commands are written to the RX characteristic; replies arrive as
notifications on the TX characteristic.
"""

DEVICE_NAME = "Adaptalux3"  # advertised name, only while the pod is in Bluetooth mode
SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # pod -> host (notifications)
RX_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"  # host -> pod (write with response)

CMD_STATUS = bytes([0x23])  # ask for the 11-byte status reply
CMD_START = bytes([0x24])  # sent by the iPhone app after connecting
