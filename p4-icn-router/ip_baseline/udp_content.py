"""UDP content request/response (aligned with pit_table ICN payload size)."""
from scapy.all import BitField, Packet, StrFixedLenField, UDP, bind_layers

REQUEST_PORT = 9999
CLIENT_PORT = 50001


class udp_request(Packet):
    """Request: content_id + flag + hop_count (same fields as ICN Interest)."""
    name = "udp_request"
    fields_desc = [
        BitField("content_id", 0, 32),
        BitField("flag", 0, 8),
        BitField("hop_count", 0, 8),
    ]


class udp_response(Packet):
    """Response: content_id + flag + 256B data (same as ICN payload)."""
    name = "udp_response"
    fields_desc = [
        BitField("content_id", 0, 32),
        BitField("flag", 0, 8),
        StrFixedLenField("data", "", 256),
    ]


bind_layers(UDP, udp_request, dport=REQUEST_PORT)
bind_layers(UDP, udp_response, sport=REQUEST_PORT)

REQUEST_LEN = 6  # bytes: 4 + 1 + 1
RESPONSE_HDR_LEN = 5  # content_id + flag before data
