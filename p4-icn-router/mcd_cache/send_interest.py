#!/usr/bin/env python3
import argparse
import random
import socket

from interest_header import interest
from payload_header import payload
from scapy.all import IP, UDP, Ether, get_if_hwaddr, get_if_list, sendp

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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('content_id', type=int, help='The Interest content_id to use, if unspecified then Interest header will not be included in packet')
    args = parser.parse_args()

    content_id = args.content_id
    iface = get_if()

    pkt =  Ether(src=get_if_hwaddr(iface), dst='08:00:00:00:01:00', type=0x88B5)
    pkt = pkt / interest(content_id=content_id, type = 0x11, hop_count=4, flag = 1, src='10.0.1.1') / UDP(dport=1234, sport=random.randint(49152,65535)) / payload(data='') 

    pkt.show2()
#    hexdump(pkt)
#    print "len(pkt) = ", len(pkt)
    sendp(pkt, iface=iface, verbose=False)


if __name__ == '__main__':
    main()
