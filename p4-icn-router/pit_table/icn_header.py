from scapy.all import *

TYPE_IPV4 = 0x0800
#TYPE_UDP = 0x11
#TYPE_TCP = 0x6


class icn(Packet):
    name = "icn"
    fields_desc = [
        BitField("content_id", 0, 32),    # コンテンツID
        BitField("type", 0, 16), #上位階層プロトコル
        #BitField("index", 0, 8),
        #BitField("src_router_id", 0, 16),
        BitField("flag", 0, 8),
        BitField("hop_count", 0, 8),       # ホップカウント
    ]

bind_layers(Ether, icn, type=0x88B5)  
