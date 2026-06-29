from scapy.all import *

class payload(Packet):
    name = "payload"
    fields_desc = [
        BitField("content_id", 0, 32),    # コンテンツID
        BitField("total_chunks", 0, 16),    #追加：全パケット数
        BitField("chunk_id", 0, 16),        #追加：このパケットの番号(0, 1, 2, ...)
        BitField("flag", 0, 8),
        BitField("source_switch", 0, 8),    # 0=producer, 1..3=s1..s3
        StrFixedLenField("data", "", 256)
    ]

bind_layers(Ether, payload, type=0x88B6)
