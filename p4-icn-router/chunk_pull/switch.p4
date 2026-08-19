/* -*- P4_16 -*- */
/* Method A: Consumer sends one Interest per chunk (chunk_id in Interest header).
 * No clone/recirculate — each cache hit returns a single Data packet.
 */
#include <core.p4>
#include <v1model.p4>

const bit<16> TYPE_IPV4 = 0x800;

typedef bit<9> egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ipv4Addr_t;

header EthernetHeader {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16> etherType;
}

header ICNHeader {
    bit<32> content_id;
    bit<16> type;
    bit<8> flag;
    bit<8> source_switch;
    bit<16> chunk_id;  // requested chunk (0 .. total-1)
}

header payload_t {
    bit<32> content_id;
    bit<16> total_chunks;
    bit<16> chunk_id;
    bit<8> flag;
    bit<8> source_switch;
    bit<2048> data;
}

struct headers {
    EthernetHeader ethernet;
    ICNHeader icn;
    payload_t payload;
}

struct metadata {
    bit<8> local_switch_id;
}

parser MyParser(packet_in pkt,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {
    state start {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            0x88B5: parse_icn;
            0x88B6: parse_payload;
            default: accept;
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

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {
    register<bit<2048>>(10240) content_cache;
    register<bit<9>>(1024) pit_table;
    register<bit<16>>(1024) total_chunks_reg;
    register<bit<8>>(1) switch_id_reg;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action set_local_switch_id(bit<8> switch_id) {
        switch_id_reg.write(0, switch_id);
        meta.local_switch_id = switch_id;
    }

    table switch_config {
        key = {
            hdr.ethernet.etherType: exact;
        }
        actions = {
            set_local_switch_id;
            NoAction;
        }
        default_action = NoAction();
        size = 4;
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
        bit<32> index = (bit<32>)hdr.payload.content_id * 10 + (bit<32>)hdr.payload.chunk_id;
        content_cache.write(index, hdr.payload.data);
        total_chunks_reg.write((bit<32>)hdr.payload.content_id, hdr.payload.total_chunks);
        hdr.payload.flag = 0;
    }

    action clear_cached_chunk(bit<32> content_id, bit<16> chunk_id) {
        bit<32> index = content_id * 10 + (bit<32>)chunk_id;
        content_cache.write(index, 0);
    }

    action serve_cached_chunk(bit<16> chunk_id, bit<32> content_id) {
        bit<32> index = (bit<32>)content_id * 10 + (bit<32>)chunk_id;
        bit<2048> cached_data;
        bit<8> sw_id;

        content_cache.read(cached_data, index);
        switch_id_reg.read(sw_id, 0);

        hdr.payload.setValid();
        hdr.payload.data = cached_data;
        hdr.payload.content_id = content_id;
        hdr.payload.chunk_id = chunk_id;
        total_chunks_reg.read(hdr.payload.total_chunks, content_id);
        hdr.payload.flag = 1;
        hdr.payload.source_switch = sw_id;
        hdr.ethernet.etherType = 0x88B6;
        hdr.icn.setInvalid();
    }

    action dup_interest(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
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
        switch_config.apply();

        if (hdr.icn.isValid()) {
            bit<2048> cached_data;
            bit<32> req_index = (bit<32>)hdr.icn.content_id * 10 + (bit<32>)hdr.icn.chunk_id;
            content_cache.read(cached_data, req_index);

            if (cached_data != 0) {
                bit<32> cid = hdr.icn.content_id;
                bit<16> req_chunk = hdr.icn.chunk_id;
                bit<8> edge_flag = hdr.icn.flag;
                pit_table.write(cid, standard_metadata.ingress_port);
                serve_cached_chunk(req_chunk, cid);
                data_forward();
                if (edge_flag != 1) {
                    clear_cached_chunk(cid, req_chunk);
                }
            } else {
                hdr.icn.flag = 0;
                pit_table.write(hdr.icn.content_id, standard_metadata.ingress_port);
                foward_interest.apply();
            }
        } else if (hdr.payload.isValid()) {
            if (hdr.payload.flag == 1) {
                cache_content();
            }
            data_forward();
        }
    }
}

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {  }
}

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}

control MyDeparser(packet_out pkt, in headers hdr) {
    apply {
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.icn);
        pkt.emit(hdr.payload);
    }
}

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
