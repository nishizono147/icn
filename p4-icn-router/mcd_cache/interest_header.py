from scapy.all import *

TYPE_IPV4 = 0x0800
TYPE_UDP = 0x11
TYPE_TCP = 0x6


class interest(Packet):
    name = "interest"
    fields_desc = [
        BitField("content_id", 0, 32),    # コンテンツID
        BitField("type", 0, 16), #上位階層プロトコル
        #BitField("index", 0, 8),
        #BitField("src_router_id", 0, 16),
        BitField("flag", 0, 8),
        BitField("hop_count", 0, 8),       # ホップカウント
        IPField("src", "0.0.0.0")
    ]

bind_layers(Ether, interest, type=0x88B5)  
bind_layers(interest, UDP, type = TYPE_UDP)
bind_layers(interest, TCP, type = TYPE_TCP)
