#!/usr/bin/env python3
import argparse
import random
import socket
import os
import sys

from interest_header import interest
from payload_header import payload
from scapy.all import IP, TCP, UDP, Ether, get_if_hwaddr, get_if_list, sendp, sniff

TYPE_IPV4 = 0x0800
TYPE_UDP = 0x11
TYPE_TCP = 0x6

# Mapping content_id to image paths
CONTENT_IMAGE_MAP = {
    1: "image1.png",
    2: "image2.png",
    3: "image3.png"
}

def get_if():
    ifs=get_if_list()
    iface=None # "h1-eth0"
    for i in get_if_list():
        if "eth0" in i:
            iface=i
            break;
    if not iface:
        print("Cannot find eth0 interface")
        exit(1)
    return iface

def read_image(file_path):
    try:
        with open(file_path, 'rb') as f:
            return f.read()
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None

def handle_pkt(packet):
    if interest in packet and (UDP in packet and packet[UDP].dport == 1234):
        print("got a packet")
        packet.show2()
        content_id = packet[interest].content_id
        image_path = CONTENT_IMAGE_MAP.get(content_id)
        if not image_path:
            print(f"No image mapped for content_id: {content_id}")
            return

        image_data = read_image(image_path)
        if not image_data:
            print(f"Failed to read image for content_id: {content_id}")
            return
        
        iface = get_if()
        pkt = Ether(src=get_if_hwaddr(iface), dst=packet[Ether].src)
        pkt = pkt / IP(dst=packet[interest].src) / TCP(dport=1234, sport=random.randint(49152, 65535)) / payload(content_id=packet[interest].content_id, flag=1, data=image_data)

        pkt.show2()
        sendp(pkt, iface=iface, verbose=False)

#        hexdump(pkt)
#        print "len(pkt) = ", len(pkt)
        sys.stdout.flush()

def main():
    ifaces = [i for i in os.listdir('/sys/class/net/') if 'eth' in i]
    iface = ifaces[0]
    print("sniffing on %s" % iface)
    sys.stdout.flush()
    sniff(iface = iface,
          prn = lambda x: handle_pkt(x))


if __name__ == '__main__':
    main()
