/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

const bit<16> TYPE_IPV4 = 0x800;
const bit<8> FL_SERVE = 1;
const bit<32> CLONE_SERVE_SESSION = 100;

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
    bit<8> hop_count;
}

header payload_t {
    bit<32> content_id;
    bit<16> total_chunks;
    bit<16> chunk_id;
    bit<8> flag;
    bit<2048> data;
}

struct headers {
    EthernetHeader ethernet;
    ICNHeader icn;
    payload_t payload;
}

struct metadata {
    @field_list(FL_SERVE)
    bit<32> serve_content_id;
    @field_list(FL_SERVE)
    bit<16> serve_total;
    @field_list(FL_SERVE)
    bit<16> current_chunk;
    @field_list(FL_SERVE)
    bit<1>  serving_from_cache;
    @field_list(FL_SERVE)
    bit<1>  clear_cache_after_serve;
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

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action data_forward() {
        bit<9> egress_port;
        pit_table.read(egress_port, hdr.payload.content_id);
        standard_metadata.egress_spec = egress_port;

        if (hdr.payload.chunk_id + 1 == hdr.payload.total_chunks) {
            pit_table.write(hdr.payload.content_id, 0);
        }

        hdr.ethernet.srcAddr = 0xFFFFFFFFFFFF;
        hdr.ethernet.dstAddr = 0xFFFFFFFFFFFF;
    }

    action cache_content() {
        bit<32> index = (bit<32>)hdr.payload.content_id * 10 + (bit<32>)hdr.payload.chunk_id;
        content_cache.write(index, hdr.payload.data);
        total_chunks_reg.write((bit<32>)hdr.payload.content_id, hdr.payload.total_chunks);
        hdr.payload.flag = 0;
    }

    action clear_content_cache(bit<32> content_id) {
        bit<32> base = content_id * 10;
        content_cache.write(base + 0, 0);
        content_cache.write(base + 1, 0);
        content_cache.write(base + 2, 0);
        content_cache.write(base + 3, 0);
        content_cache.write(base + 4, 0);
        content_cache.write(base + 5, 0);
        content_cache.write(base + 6, 0);
        content_cache.write(base + 7, 0);
        content_cache.write(base + 8, 0);
        content_cache.write(base + 9, 0);
        total_chunks_reg.write(content_id, 0);
    }

    action serve_cached_chunk(bit<16> chunk_id, bit<32> content_id) {
        bit<32> index = (bit<32>)content_id * 10 + (bit<32>)chunk_id;
        bit<2048> cached_data;

        content_cache.read(cached_data, index);

        hdr.payload.setValid();
        hdr.payload.data = cached_data;
        hdr.payload.content_id = content_id;
        hdr.payload.chunk_id = chunk_id;
        total_chunks_reg.read(hdr.payload.total_chunks, content_id);
        hdr.payload.flag = 1;
        hdr.ethernet.etherType = 0x88B6;
        hdr.icn.setInvalid();

        meta.current_chunk = chunk_id + 1;
    }

    action queue_next_chunk_clone() {
        if (meta.current_chunk < meta.serve_total) {
            clone_preserving_field_list(CloneType.I2E, CLONE_SERVE_SESSION, FL_SERVE);
        } else {
            if (meta.clear_cache_after_serve == 1) {
                clear_content_cache(meta.serve_content_id);
            }
            meta.serving_from_cache = 0;
            meta.clear_cache_after_serve = 0;
        }
    }

    action continue_cache_serve() {
        serve_cached_chunk(meta.current_chunk, meta.serve_content_id);
        data_forward();
        queue_next_chunk_clone();
    }

    action begin_cache_serve() {
        pit_table.write(hdr.icn.content_id, standard_metadata.ingress_port);
        meta.serving_from_cache = 1;
        meta.serve_content_id = hdr.icn.content_id;
        meta.clear_cache_after_serve = (hdr.icn.flag != 1) ? 1w1 : 1w0;
        total_chunks_reg.read(meta.serve_total, (bit<32>)hdr.icn.content_id);

        if (meta.serve_total > 1) {
            meta.current_chunk = 1;
            clone_preserving_field_list(CloneType.I2E, CLONE_SERVE_SESSION, FL_SERVE);
        }

        serve_cached_chunk(0, hdr.icn.content_id);
        data_forward();

        if (meta.serve_total <= 1) {
            if (meta.clear_cache_after_serve == 1) {
                clear_content_cache(meta.serve_content_id);
            }
            meta.serving_from_cache = 0;
            meta.clear_cache_after_serve = 0;
        }
    }

    action dup_interest(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
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
        if (hdr.icn.isValid()) {
            if (meta.serving_from_cache == 1 && meta.current_chunk > 0) {
                continue_cache_serve();
            } else {
                bit<2048> cached_data;
                bit<32> base_index = (bit<32>)hdr.icn.content_id * 10;
                content_cache.read(cached_data, base_index);

                if (cached_data != 0) {
                    begin_cache_serve();
                } else {
                    meta.serving_from_cache = 0;
                    meta.current_chunk = 0;
                    hdr.icn.flag = 0;
                    pit_table.write(hdr.icn.content_id, standard_metadata.ingress_port);
                    foward_interest.apply();
                }
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
    apply {
        if (meta.serving_from_cache == 1
            && hdr.icn.isValid()
            && meta.current_chunk > 0
            && meta.current_chunk < meta.serve_total) {
            recirculate_preserving_field_list(FL_SERVE);
        }
    }
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
