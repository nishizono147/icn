from scapy.all import *

class payload(Packet):
    name = "payload"
    fields_desc = [
        BitField("content_id", 0, 32),
        BitField("total_chunks", 0, 16),
        BitField("chunk_id", 0, 16),
        BitField("flag", 0, 8),
        BitField("source_switch", 0, 8),
        StrFixedLenField("data", "", 256),
    ]

bind_layers(Ether, payload, type=0x88B6)
