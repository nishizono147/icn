"""UDP content request/response aligned with chunk_table payload layout."""
from scapy.all import BitField, Packet, StrFixedLenField, UDP, bind_layers

REQUEST_PORT = 9999
CLIENT_PORT = 50001
CHUNK_SIZE = 256


class udp_request(Packet):
    """Request: content_id + flag + hop_count (same fields as ICN Interest)."""
    name = "udp_request"
    fields_desc = [
        BitField("content_id", 0, 32),
        BitField("flag", 0, 8),
        BitField("hop_count", 0, 8),
    ]


class udp_response(Packet):
    """Response: matches chunk_table payload header + 256B data."""
    name = "udp_response"
    fields_desc = [
        BitField("content_id", 0, 32),
        BitField("total_chunks", 0, 16),
        BitField("chunk_id", 0, 16),
        BitField("flag", 0, 8),
        BitField("reserved", 0, 8),
        StrFixedLenField("data", "", CHUNK_SIZE),
    ]


bind_layers(UDP, udp_request, dport=REQUEST_PORT)
bind_layers(UDP, udp_response, sport=REQUEST_PORT)

REQUEST_LEN = 6
