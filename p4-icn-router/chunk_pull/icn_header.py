from scapy.all import *

class icn(Packet):
    name = "icn"
    fields_desc = [
        BitField("content_id", 0, 32),
        BitField("type", 0, 16),
        BitField("flag", 0, 8),
        BitField("source_switch", 0, 8),
        BitField("chunk_id", 0, 16),  # Method A: requested chunk index
    ]

bind_layers(Ether, icn, type=0x88B5)
