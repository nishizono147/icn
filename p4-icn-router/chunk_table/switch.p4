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
    bit<16> total_chunks;   // 追加：全パケット数
    bit<16> chunk_id;       // 追加：現在のパケット番号
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
    bit<16> current_chunk; // 追加：現在何番目を処理しているか
    bit<1> is_recirculated; // 追加：再循環中かどうかのフラグ
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
    // 倉庫のサイズを 1024 * 10 (10分割分)
    register<bit<2048>>(10240) content_cache;
    register<bit<9>>(1024) pit_table;

    // コンテンツごとに「総パケット数」を覚えておくレジスタ
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
        
        // インデックスを計算: (content_id * 10) + chunk_id
        // これにより、同じコンテンツIDでも番号ごとに違う場所に保存される
        bit<32> index = (bit<32>)hdr.payload.content_id * 10 + (bit<32>)hdr.payload.chunk_id;

        content_cache.write(index, hdr.payload.data);

        // 総パケット数も保存しておく（後でまとめて送るため）
        total_chunks_reg.write((bit<32>)hdr.payload.content_id, hdr.payload.total_chunks);

        content_cache.write(hdr.payload.content_id, hdr.payload.data); //ここでキャッシュ、、変更したたた

        hdr.payload.flag = 0;
    }

    /*action return_content() {
        bit<2048> cached_data;
        content_cache.read(cached_data, hdr.icn.content_id); //キャッシュ読み取り
        hdr.payload.setValid();  //ペイロードを有効化
        hdr.payload.data = cached_data; //書き込み
        hdr.payload.content_id = hdr.icn.content_id;
        hdr.payload.flag = 1;
        hdr.ethernet.etherType = 0x88B6;
        hdr.icn.setInvalid();
    }*/

    action return_content_chunk(bit<16> chunk_id) {
        // 倉庫のインデックス計算: (ID * 10) + chunk_id
        bit<32> index = (bit<32>)hdr.icn.content_id * 10 + (bit<32>)chunk_id;
    
        bit<2048> cached_data;
        content_cache.read(cached_data, index);
    
        // パケットをData用に加工
        hdr.payload.setValid();
        hdr.payload.data = cached_data;
        hdr.payload.content_id = hdr.icn.content_id;
        hdr.payload.chunk_id = chunk_id;

        // 総パケット数もレジスタから読み取ってヘッダーに入れる
        total_chunks_reg.read(hdr.payload.total_chunks, (bit<32>)hdr.icn.content_id);

        hdr.payload.flag = 1;
        hdr.ethernet.etherType = 0x88B6;
    
        // 注文票（ICN）はもう不要なので無効化
        hdr.icn.setInvalid();

        // 次のループのための準備
        meta.current_chunk = chunk_id + 1;
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


    /*apply {
        bit<2048> cached_data;

        if (hdr.icn.isValid()) {                                   //Interestを受信したら
            content_cache.read(cached_data, hdr.icn.content_id);   //キャッシュがあるか確認
            if (cached_data != 0) {                                //キャッシュがあったら
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
    }*/

    apply {
        // --- [初期化処理] ---
        // 通常、外部から来たパケットのmetadataは0です。
        // 再循環パケットの場合のみ、アクション内でセットした値が保持されるようにします。

        // もし外部から来た（再循環でない）パケットなら、カウンタを0にリセット
        if (standard_metadata.instance_type == 0) {
            meta.current_chunk = 0;
        }

        if (hdr.icn.isValid()) {    // Interestを受信したら

            // キャッシュがあるか確認 (0番目のデータがあるかで判定)
            bit<2048> cached_data;
            // 0番目のデータがある場所をチェック
            bit<32> base_index = (bit<32>)hdr.icn.content_id * 10;
            content_cache.read(cached_data, base_index);

            if (cached_data != 0) { // キャッシュがあったら

                // 総パケット数をレジスタから読み出す
                bit<16> total;
                total_chunks_reg.read(total, (bit<32>)hdr.icn.content_id);

                // --- [分割送信ロジック] ---
                // 現在送るべき番号を取得（初回なら0、再循環中ならメタデータから）
                // ※再循環パケットかどうかを判別するフラグを後で検討
                return_content_chunk(meta.current_chunk); 

                // まだ続き（chunk）があるなら自分に投げ直す
                if (meta.current_chunk < total) {
                    // 自分自身の ingress_port に投げ直す
                    // recirculate<metadata>(meta);  <-- これを消して、以下を追加
                    standard_metadata.egress_spec = 511; // 再循環用の特殊なポート番号
                    standard_metadata.instance_type = 1; // 再循環パケットであることを明示
                    return; // このパケットの処理をここで終えて再循環に回す
                }

                // 送信ポートの決定などは既存の data_forward を利用
                data_forward();
            } else {
                // キャッシュがない場合の既存ロジック
                hdr.icn.flag = 0;
                pit_table.write(hdr.icn.content_id, standard_metadata.ingress_port);
                foward_interest.apply();
            }
        } else if (hdr.payload.isValid()) {
            // Dataパケットを受信した時の既存ロジック（そのまま）
            // 外部から届いたDataをキャッシュする既存ロジック
            if (hdr.payload.flag == 1) {
                cache_content(); 
            }
            data_forward();
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