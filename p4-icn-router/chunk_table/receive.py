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

"""
# グローバル変数を受信待ち受け状態にする
received_chunks = {}

def handle_pkt(pkt): # 引数を元のコードに合わせて pkt に
    if payload in pkt:
        # パケットから情報を取り出す
        c_id = pkt[payload].content_id
        chunk_id = pkt[payload].chunk_id
        total = pkt[payload].total_chunks
        data = pkt[payload].data
        
        print(f"Got chunk {chunk_id + 1}/{total} for content_id {c_id}")

        # 辞書に保存（番号をキーにする）
        received_chunks[chunk_id] = data

        # 全部揃ったか判定
        if len(received_chunks) == total:
            print("All chunks received! Reassembling...")
            
            # 番号順に連結
            full_binary = b""
            for i in range(total):
                full_binary += received_chunks[i]
            
            # 保存先のファイル名（例: received_image4.png）
            out_file = f"received_image{c_id}.png"
            with open(out_file, "wb") as f:
                f.write(full_binary)
            
            print(f"Successfully saved: {out_file}")
            
            # 次のデータ受信のために辞書を空にする
            received_chunks.clear()
"""
"""
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
"""

buffers = {}
chunk_counts = {}

def handle_pkt(pkt):
    if payload in pkt:
        cid = pkt[payload].content_id
        chunk_id = pkt[payload].chunk_id
        total = pkt[payload].total_chunks
        data = bytes(pkt[payload].data)

        # 初めて見るcontent_idなら初期化
        if cid not in buffers:
            buffers[cid] = {}
            chunk_counts[cid] = total
            print(f"Start receiving content_id {cid} ({total} chunks)")

        # 受信したチャンクを保存
        buffers[cid][chunk_id] = data

        # 進捗ログを出力
        print(f"Got chunk {chunk_id + 1}/{total} for content_id {cid}")

        # 全チャンク揃ったか確認
        if len(buffers[cid]) == chunk_counts[cid]:
            print("All chunks received! Reassembling...")

            # chunk_id順に連結して復元
            full = b''.join(buffers[cid][i] for i in range(total))

            # 保存
            save_image(full, cid)

            print(f"Successfully reconstructed content_id {cid}")
            
            # 後処理
            del buffers[cid]
            del chunk_counts[cid]



def main():
    ifaces = [i for i in os.listdir('/sys/class/net/') if 'eth' in i]
    iface = ifaces[0]
    print("sniffing on %s" % iface)
    sys.stdout.flush()
    sniff(iface = iface,
          prn = lambda x: handle_pkt(x))

if __name__ == '__main__':
    main()
