/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

const bit<16> TYPE_IPV4 = 0x800;
/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/
typedef bit<9> egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ipv4Addr_t;

// Header Definitions
header EthernetHeader {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16> etherType;
}

header IPv4Header {
    bit<4> version;
    bit<4> ihl;
    bit<8> diffserv;
    bit<16> totalLen;
    bit<16> identification;
    bit<3> flags;
    bit<13> fragOffset;
    bit<8> ttl;
    bit<8> protocol;
    bit<16> hdrChecksum;
    bit<32> srcAddr;
    bit<32> dstAddr;
}

header UDPHeader {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<16> length;
    bit<16> checksum;
}

header InterestHeader {
    bit<32> content_id;    // Content ID
    bit<16> type;
    //bit<16> src_router_id; // Source Router ID
    bit<8> flag;
    bit<8> hop_count;      // Hop Count
    bit<32> src;
}

header TCPHeader {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<32> seqNo;
    bit<32> ackNo;
    bit<4> dataOffset;
    bit<4> reserved;
    bit<8> flags;
    bit<16> window;
    bit<16> checksum;
    bit<16> urgentPtr;
}

header payload_t {
    bit<32> content_id;
    bit<8> flag;
    bit<2048> data;
}

// Header Structure
struct headers {
    EthernetHeader ethernet;
    IPv4Header ipv4;
    UDPHeader udp;
    InterestHeader interest;
    TCPHeader tcp;
    payload_t payload;
}

struct metadata {
    bit<1> is_cached;
    bit<32> cached_content;
}
/*************************************************************************
*********************** P A R S E R  ***********************************
*************************************************************************/
parser MyParser(packet_in pkt,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {
    state start {
        pkt.extract(hdr.ethernet); // Ethernetヘッダを解析
        transition select(hdr.ethernet.etherType) {
            0x0800: parse_ipv4; // IPv4パケットの場合
            0x88B5: parse_interest;
            default: accept;   // その他はそのまま受け入れる
        }
    }

    state parse_ipv4 {
        pkt.extract(hdr.ipv4); // IPv4ヘッダを解析
        transition select(hdr.ipv4.protocol) {
            0x6: parse_tcp;  // interestプロトコルの場合
            default: accept; // その他は受け入れる
        }
    }

    state parse_interest {
        pkt.extract(hdr.interest);
        transition select(hdr.interest.type) {
            0x11: parse_udp;
            0x6: parse_tcp;
            default: accept;
        }
    }

    state parse_udp {
        pkt.extract(hdr.udp); // UDPヘッダを解析
        transition parse_payload;
    }

    state parse_tcp {
        pkt.extract(hdr.tcp); // Interestヘッダを解析
        transition parse_payload;
    }

    state parse_payload {
        pkt.extract(hdr.payload);
        transition accept;
    }
}

/*************************************************************************
************   C H E C K S U M    V E R I F I C A T I O N   *************
*************************************************************************/

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}

/*************************************************************************
**************  I N G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {
    register<bit<2048>>(1024) content_cache;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ipv4_forward(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
	//hdr.interest.hop_count = hdr.interest.hop_count - 1;
    }

    table ipv4_lpm {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            ipv4_forward;
            drop;
        }
        size = 1024;
        default_action = drop();
    }

    action cache_content() {
        content_cache.write(hdr.payload.content_id, hdr.payload.data); //ここでキャッシュ
        hdr.payload.flag = 0;
    }

    action return_content() {
	bit<2048> cached_data;
        content_cache.read(cached_data, hdr.interest.content_id); //キャッシュ読み取り
        //hdr.payload.setValid();  //ペイロードを有効化
        hdr.payload.data = cached_data; //書き込み
        hdr.ipv4.setValid(); //IPヘッダを有効化
        hdr.ethernet.etherType = 0x0800;
        hdr.ipv4.dstAddr = hdr.interest.src; //宛先IPアドレスを送信元IPアドレスに変更
        hdr.ipv4.srcAddr = hdr.interest.src;
        hdr.ipv4.ttl = 64;
        hdr.ipv4.protocol = 0x6;
	hdr.ipv4.version = 4;
	hdr.ipv4.ihl = 5;
	hdr.ipv4.diffserv = 0;
	hdr.ipv4.identification = 0;
	hdr.ipv4.totalLen = 281;
	hdr.ipv4.flags = 2;
	hdr.ipv4.fragOffset = 0;
	hdr.ipv4.hdrChecksum = 0;
        hdr.tcp.setValid();  //TCPヘッダを有効化
	//hdr.interest.hop_count = 5;
        hdr.tcp.srcPort = hdr.udp.srcPort;  // UDPの送信元ポートをコピー
        hdr.tcp.dstPort = hdr.udp.dstPort;  // UDPの宛先ポートをコピー
	hdr.udp.setInvalid(); //UDP無効
        hdr.tcp.seqNo = 0;                 // シーケンス番号を初期化
        hdr.tcp.ackNo = 0;                 // ACK番号を初期化
        hdr.tcp.dataOffset = 5;            // デフォルト（5×4バイト = 20バイトヘッダ）
        hdr.tcp.flags = 0x02;              // SYNフラグを設定
        hdr.tcp.window = 8192;             // ウィンドウサイズを設定
        hdr.tcp.checksum = 0;              // チェックサムは再計算される可能性あり
        hdr.tcp.urgentPtr = 0;             // 緊急ポインタをクリア
        hdr.payload.flag = 1;
        hdr.payload.content_id = hdr.interest.content_id;
        hdr.interest.setInvalid();
	//hdr.interest.hop_count = hdr.interest.hop_count - 1;
    }

    action dup_interest(macAddr_t dstAddr, egressSpec_t port) {
        //standard_metadata.mcast_grp = 1;
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
        //hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        hdr.interest.hop_count = hdr.interest.hop_count - 1;
    }

    table foward_interest {
        key = {
            hdr.ethernet.srcAddr: exact;
        }
        actions = {
            dup_interest;
            drop;
        }
        size = 1024;
        default_action = drop;
    }


    apply {
        bit<2048> cached_data;

        if (hdr.interest.isValid()) {                                    //UDPだったら(Interest)
            content_cache.read(cached_data, hdr.interest.content_id);   //キャッシュがあるか確認
            if (cached_data != 0) {                                //キャッシュがあったら
                if (hdr.interest.flag == 1) {
		    return_content();
                } else {
		    return_content();
                    content_cache.write(hdr.payload.content_id, 0); //remove cached data
                }
                ipv4_lpm.apply();                                  //フォワーディング
            } else {
		hdr.interest.flag = 0;
                foward_interest.apply();  //Interestを複製            
            }
        } else {
            if (hdr.payload.flag == 1) {
                cache_content();                            //TCPだったらキャッシュ
            }
            ipv4_lpm.apply();                         //フォワーディング
        }
    }
}

/*************************************************************************
****************  E G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {  }
}

/*************************************************************************
*************   C H E C K S U M    C O M P U T A T I O N   **************
*************************************************************************/

control MyComputeChecksum(inout headers  hdr, inout metadata meta) {
     apply {
        update_checksum(
            hdr.ipv4.isValid(),
            { hdr.ipv4.version,
              hdr.ipv4.ihl,
              hdr.ipv4.diffserv,
              hdr.ipv4.totalLen,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.fragOffset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16);
    }
}

/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/
control MyDeparser(packet_out pkt, in headers hdr) {
    apply {
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.ipv4);
	pkt.emit(hdr.interest);
	pkt.emit(hdr.tcp);
	pkt.emit(hdr.udp);
	pkt.emit(hdr.payload);
    }
}
/*************************************************************************
***********************  S W I T C H  *******************************
*************************************************************************/
V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
    ) main;