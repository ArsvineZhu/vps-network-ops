/* SPDX-License-Identifier: GPL-2.0-only
 * Fixed-layout IPv4 SYN option reordering. No TCP negotiation values change.
 * Never infer skb checksum state from packet bytes. Kernel helpers preserve it.
 */
#include <linux/bpf.h>
#include <linux/pkt_cls.h>
#include <bpf/bpf_endian.h>
#include <bpf/bpf_helpers.h>

#define ETH_HLEN 14
#define IP_HLEN 20
#define TCP_HLEN 20
#define MARK_WIN 0x10
#define MARK_IOS 0x20

enum {
    ST_SEEN,
    ST_WIN_OK,
    ST_IOS_OK,
    ST_SKIP,
    ST_ERR_TAIL,
    ST_ERR_STORE,
    ST_ERR_CSUM,
    ST_ERR_LOAD,
    ST_ERR_LAYOUT,
    ST_DROP,
    ST_COUNT
};

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, ST_COUNT);
    __type(key, __u32);
    __type(value, __u64);
} stats SEC(".maps");
char LICENSE[] SEC("license") = "GPL";

static __always_inline void stat_inc(__u32 key) {
    __u64 *v = bpf_map_lookup_elem(&stats, &key);
    if (v)
        __sync_fetch_and_add(v, 1);
}

static __always_inline int drop_error(__u32 key) {
    stat_inc(key);
    stat_inc(ST_DROP);
    return TC_ACT_SHOT;
}

/* Only Ethernet IPv4, no fragmentation/IP options/payload/padding. ECN and
 * low doff nibble are preserved. FIN/RST/ACK/PSH/URG on SYN are not supported.
 * No packet writes occur here. */
static __always_inline int parse_syn(struct __sk_buff *skb, __u32 *opt_len) {
    __u8 eth[14], ip[20], tcp[20];
    __u16 total;
    if (skb->len < ETH_HLEN + IP_HLEN + TCP_HLEN)
        return 0;
    if (bpf_skb_load_bytes(skb, 0, eth, sizeof(eth)) < 0 ||
        bpf_skb_load_bytes(skb, ETH_HLEN, ip, sizeof(ip)) < 0 ||
        bpf_skb_load_bytes(skb, ETH_HLEN + IP_HLEN, tcp, sizeof(tcp)) < 0)
        return -1;
    if (eth[12] != 0x08 || eth[13] != 0 || ip[0] != 0x45 || ip[9] != 6)
        return 0;
    /* Reserved IPv4 flag, MF or fragment offset: skip; DF is permitted. */
    if ((ip[6] & 0xbf) || ip[7])
        return 0;
    total = (__u16)(((__u16)ip[2] << 8) | ip[3]);
    if (skb->len != (__u32)ETH_HLEN + total || total < IP_HLEN + TCP_HLEN)
        return 0;
    if (!(tcp[13] & 0x02) || (tcp[13] & 0x3d))
        return 0;
    if ((tcp[12] >> 4) < 5 || total != IP_HLEN + ((tcp[12] >> 4) * 4))
        return 0;
    *opt_len = ((__u32)(tcp[12] >> 4) * 4) - TCP_HLEN;
    return 1;
}

static __always_inline int rewrite_win(struct __sk_buff *skb) {
    __u32 len;
    __u8 old[12], new[12];
    int r;
    stat_inc(ST_SEEN);
    r = parse_syn(skb, &len);
    if (r <= 0) {
        stat_inc(r < 0 ? ST_ERR_LOAD : ST_SKIP);
        return TC_ACT_OK;
    }
    if (len != 12) {
        stat_inc(ST_ERR_LAYOUT);
        return TC_ACT_OK;
    }
    if (bpf_skb_load_bytes(skb, 54, old, sizeof(old)) < 0) {
        stat_inc(ST_ERR_LOAD);
        return TC_ACT_OK;
    }
    if (!(old[0] == 2 && old[1] == 4 && old[4] == 1 && old[5] == 1 && old[6] == 4 && old[7] == 2 &&
          old[8] == 1 && old[9] == 3 && old[10] == 3)) {
        stat_inc(ST_ERR_LAYOUT);
        return TC_ACT_OK;
    }
    new[0] = old[0];
    new[1] = old[1];
    new[2] = old[2];
    new[3] = old[3];
    new[4] = old[8];
    new[5] = old[9];
    new[6] = old[10];
    new[7] = old[11];
    new[8] = old[4];
    new[9] = old[5];
    new[10] = old[6];
    new[11] = old[7];
    /* Same aligned 16-bit words, only reordered: sum is exactly unchanged.
     * Correct for both a full checksum and a PARTIAL pseudoheader seed.
     * COMPLETE metadata is unchanged for the same reason. */
    if (bpf_skb_store_bytes(skb, 54, new, sizeof(new), 0) < 0)
        return drop_error(ST_ERR_STORE);
    stat_inc(ST_WIN_OK);
    return TC_ACT_OK;
}

static __always_inline int rewrite_ios(struct __sk_buff *skb) {
    __u32 len;
    /* Four-byte alignment is required by bpf_csum_diff, including stack data. */
    __u8 old[20] __attribute__((aligned(4)));
    __u8 new[24] __attribute__((aligned(4)));
    __u16 offset_flags, new_offset_flags;
    __u8 off[2];
    __s64 diff;
    int r;
    stat_inc(ST_SEEN);
    r = parse_syn(skb, &len);
    if (r <= 0) {
        stat_inc(r < 0 ? ST_ERR_LOAD : ST_SKIP);
        return TC_ACT_OK;
    }
    if (len != 20) {
        stat_inc(ST_ERR_LAYOUT);
        return TC_ACT_OK;
    }
    if (bpf_skb_load_bytes(skb, 54, old, sizeof(old)) < 0 ||
        bpf_skb_load_bytes(skb, 46, off, sizeof(off)) < 0) {
        stat_inc(ST_ERR_LOAD);
        return TC_ACT_OK;
    }
    if (!(old[0] == 2 && old[1] == 4 && old[4] == 4 && old[5] == 2 && old[6] == 8 && old[7] == 10 &&
          old[16] == 1 && old[17] == 3 && old[18] == 3)) {
        stat_inc(ST_ERR_LAYOUT);
        return TC_ACT_OK;
    }
    new[0] = old[0];
    new[1] = old[1];
    new[2] = old[2];
    new[3] = old[3];
    new[4] = old[16];
    new[5] = old[17];
    new[6] = old[18];
    new[7] = old[19];
    new[8] = 1;
    new[9] = 1;
    new[10] = 8;
    new[11] = 10;
    new[12] = old[8];
    new[13] = old[9];
    new[14] = old[10];
    new[15] = old[11];
    new[16] = old[12];
    new[17] = old[13];
    new[18] = old[14];
    new[19] = old[15];
    new[20] = 4;
    new[21] = 2;
    new[22] = 0;
    new[23] = 0;
    offset_flags = bpf_htons((__u16)(((__u16)off[0] << 8) | off[1]));
    new_offset_flags = bpf_htons((__u16)(((__u16)((off[0] & 0x0f) | 0xb0) << 8) | off[1]));
    diff = bpf_csum_diff((__be32 *)old, sizeof(old), (__be32 *)new, sizeof(new), 0);
    if (diff < 0) {
        stat_inc(ST_ERR_CSUM);
        return TC_ACT_OK; /* Still entirely unchanged. */
    }

    /* First possible mutation: every failure from this point must drop.
     * change_tail may reset GSO and COMPLETE; it does NOT clear PARTIAL. */
    if (bpf_skb_change_tail(skb, skb->len + 4, 0) < 0)
        return drop_error(ST_ERR_TAIL);
    /* Ordinary TCP deltas update full checksums and leave PARTIAL seed alone. */
    if (bpf_l4_csum_replace(skb, 50, 0, (__u32)diff, 0) < 0 ||
        bpf_l4_csum_replace(skb, 50, offset_flags, new_offset_flags, 2) < 0 ||
        /* Pseudoheader length 40 -> 44 updates BOTH full and PARTIAL paths. */
        bpf_l4_csum_replace(skb, 50, bpf_htons(40), bpf_htons(44), BPF_F_PSEUDO_HDR | 2) < 0 ||
        bpf_l3_csum_replace(skb, 24, bpf_htons(60), bpf_htons(64), 2) < 0)
        return drop_error(ST_ERR_CSUM);
    __u16 total = bpf_htons(64);
    if (bpf_skb_store_bytes(skb, 54, new, sizeof(new), 0) < 0 ||
        bpf_skb_store_bytes(skb, 46, &new_offset_flags, sizeof(new_offset_flags), 0) < 0 ||
        bpf_skb_store_bytes(skb, 16, &total, sizeof(total), 0) < 0)
        return drop_error(ST_ERR_STORE);
    stat_inc(ST_IOS_OK);
    return TC_ACT_OK;
}

SEC("tc_win") int prog_win(struct __sk_buff *skb) { return rewrite_win(skb); }
SEC("tc_ios") int prog_ios(struct __sk_buff *skb) { return rewrite_ios(skb); }
SEC("tc_mark") int prog_mark(struct __sk_buff *skb) {
    if (skb->mark == MARK_WIN)
        return rewrite_win(skb);
    if (skb->mark == MARK_IOS)
        return rewrite_ios(skb);
    return TC_ACT_OK;
}
