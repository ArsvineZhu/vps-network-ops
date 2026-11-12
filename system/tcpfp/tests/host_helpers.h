/* Test-only helper ABI. Never include this header in a kernel build. */
#ifndef TCPFP_HOST_HELPERS_H
#define TCPFP_HOST_HELPERS_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <arpa/inet.h>
#include <linux/types.h>
#define SEC(x)
#ifndef __always_inline
#define __always_inline inline __attribute__((always_inline))
#endif
#define bpf_htons htons
#define BPF_F_PSEUDO_HDR 16
#define TC_ACT_OK 0
#define TC_ACT_SHOT 2
enum { CHECKSUM_NONE, CHECKSUM_UNNECESSARY, CHECKSUM_COMPLETE, CHECKSUM_PARTIAL };
struct __sk_buff { __u32 len, mark; __u8 data[256]; int state; __u32 complete_sum; };
extern __u64 host_stats[16];
int bpf_skb_load_bytes(struct __sk_buff *, __u32, void *, __u32);
int bpf_skb_store_bytes(struct __sk_buff *, __u32, const void *, __u32, __u64);
int bpf_skb_change_tail(struct __sk_buff *, __u32, __u64);
__s64 bpf_csum_diff(__be32 *, __u32, __be32 *, __u32, __u32);
int bpf_l4_csum_replace(struct __sk_buff *, __u32, __u64, __u64, __u64);
int bpf_l3_csum_replace(struct __sk_buff *, __u32, __u64, __u64, __u64);
#endif
