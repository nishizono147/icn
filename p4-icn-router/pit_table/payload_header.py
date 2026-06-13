from scapy.all import *

class payload(Packet):
    name = "payload"
    fields_desc = [
        BitField("content_id", 0, 32),    # コンテンツID
        BitField("flag", 0, 8),
        StrFixedLenField("data", "", 256)
    ]

bind_layers(Ether, payload, type=0x88B6)
