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

header ICNHeader {
    bit<32> content_id;    // Content ID
    bit<16> type;
    //bit<16> src_router_id; // Source Router ID
    bit<8> flag;
    bit<8> hop_count;      // Hop Count
}

header payload_t {
    bit<32> content_id;
    bit<8> flag;
    bit<2048> data;
}

// Header Structure
struct headers {
    EthernetHeader ethernet;
    ICNHeader icn;
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
            0x88B5: parse_icn; // IPv4パケットの場合
            0x88B6: parse_payload;
            default: accept;   // その他はそのまま受け入れる
        }
    }

    state parse_icn {
        pkt.extract(hdr.icn);
        transition accept;
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
    register<bit<9>>(1024) pit_table;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action data_forward() {
        bit<9> egress_port;
        pit_table.read(egress_port, hdr.payload.content_id);
        standard_metadata.egress_spec = egress_port;
        pit_table.write(hdr.payload.content_id, 0);
        hdr.ethernet.srcAddr = 0xFFFFFFFFFFFF;
        hdr.ethernet.dstAddr = 0xFFFFFFFFFFFF;
    }

    action cache_content() {
        content_cache.write(hdr.payload.content_id, hdr.payload.data); //ここでキャッシュ
        hdr.payload.flag = 0;
    }

    action return_content() {
        bit<2048> cached_data;
        content_cache.read(cached_data, hdr.icn.content_id); //キャッシュ読み取り
        hdr.payload.setValid();  //ペイロードを有効化
        hdr.payload.data = cached_data; //書き込み
        hdr.payload.content_id = hdr.icn.content_id;
        hdr.payload.flag = 1;
        hdr.ethernet.etherType = 0x88B6;
        hdr.icn.setInvalid();
    }

    action dup_interest(macAddr_t dstAddr, egressSpec_t port) {
        //standard_metadata.mcast_grp = 1;
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
        //hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        hdr.icn.hop_count = hdr.icn.hop_count - 1;
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

        if (hdr.icn.isValid()) {                                   //Interestを受信したら
            content_cache.read(cached_data, hdr.icn.content_id);   //キャッシュがあるか確認
            if (cached_data != 0) {                                //キャッシュがあったら
                pit_table.write(hdr.icn.content_id, standard_metadata.ingress_port);
                if (hdr.icn.flag == 1) {                           //エッジノードだったら
                    return_content();                              //キャッシュを削除せずにDataに加工
                } else {                                           //エッジノードではなかったら
                    return_content();                              //Dataに加工して
                    content_cache.write(hdr.payload.content_id, 0); //キャッシュを削除
                }
                data_forward();                                  //Dataルーティング
            } else {                                               //キャッシュがなかったら
                hdr.icn.flag = 0;                                  //Interestをフォワーディングするのでflagを0にしてエッジ検出しないようにする
                pit_table.write(hdr.icn.content_id, standard_metadata.ingress_port);  //pitテーブルにコンテンツ名と受信元ポートを記録する
                foward_interest.apply();  //Interestをフォワーディング
            }
        } else { //Dataパケットを受信したら
            if (hdr.payload.flag == 1) { //キャッシュ提案flagが1なら
                cache_content();                            //キャッシュ
            }
            data_forward();                         //Dataフォワーディング
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
    }
}

/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/
control MyDeparser(packet_out pkt, in headers hdr) {
    apply {
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.icn);
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