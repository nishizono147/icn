#!/usr/bin/env python3
import os
import sys

from icn_header import icn
from payload_header import payload
from scapy.all import IP, TCP, UDP, Ether, get_if_list, sniff


def get_if():
    ifs=get_if_list()
    iface=None
    for i in get_if_list():
        if "eth0" in i:
            iface=i
            break;
    if not iface:
        print("Cannot find eth0 interface")
        exit(1)
    return iface

def save_image(data, content_id):
    directory = "received_image"
    if not os.path.exists(directory):
        os.makedirs(directory)
    filename = os.path.join(directory, f"image{content_id}.png")
    try:
        with open(filename, 'wb') as f:
            f.write(data)
        print(f"Image saved as {filename}")
    except Exception as e:
        print(f"Failed to save image: {e}")

def handle_pkt(pkt):
    if payload in pkt :
        print("got a packet")
        pkt.show2()
        content_id = pkt[payload].content_id
        image_data = bytes(pkt[payload].data)
        save_image(image_data, content_id)
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
