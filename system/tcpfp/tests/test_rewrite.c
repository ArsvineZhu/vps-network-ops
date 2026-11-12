/* Runs the ACTUAL program functions. Helper mocks model checksum-state rules;
 * the independent wire-checksum oracle uses big-endian packet bytes. This is
 * deliberately not described as kernel execution or verifier acceptance. */
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#define TCPFP_HOST_TEST 1
#include "../ebpf/syn_rewrite.c"

__u64 host_stats[16];
static unsigned calls, fail_at, cases;
static int mutate_on_error;
static uint32_t rng = 0x90e21213;
static uint32_t random32(void) { rng ^= rng << 13; rng ^= rng >> 17; return rng ^= rng << 5; }
static int fails(void) { calls++; return fail_at == calls; }
static uint16_t fold(uint64_t n) { while(n >> 16) n = (n & 65535) + (n >> 16); return n; }
static uint16_t read_be(const uint8_t *p) { return ((uint16_t)p[0] << 8) | p[1]; }
static void put_be(uint8_t *p, uint16_t x) { p[0] = x >> 8; p[1] = x; }
static uint64_t sum_be(const uint8_t *p, unsigned len)
{ uint64_t n = 0; for (unsigned i=0; i<len; i+=2) n += ((uint16_t)p[i]<<8) | (i+1<len?p[i+1]:0); return n; }
static uint16_t pseudo(const struct __sk_buff *s)
{ return fold(sum_be(s->data+26,8) + 6 + s->len-34); }
static int wire_valid(const struct __sk_buff *s)
{ return fold(pseudo(s) + sum_be(s->data+34,s->len-34)) == 65535; }
static void complete(struct __sk_buff *s)
{
    if (s->state != CHECKSUM_PARTIAL) return;
    /* Hardware/software completion sums TCP bytes INCLUDING the seed. */
    put_be(s->data+50, (uint16_t)~fold(sum_be(s->data+34,s->len-34)));
    s->state = CHECKSUM_NONE;
}
int bpf_skb_load_bytes(struct __sk_buff *s,__u32 off,void *p,__u32 n)
{ if(fails() || off+n > s->len) return -1; memcpy(p,s->data+off,n); return 0; }
int bpf_skb_store_bytes(struct __sk_buff *s,__u32 off,const void *p,__u32 n,__u64 flags)
{
    assert(!flags);
    int error=fails();
    if(off+n > s->len) return -1;
    if(!error || mutate_on_error) memcpy(s->data+off,p,n);
    return error?-1:0;
}
int bpf_skb_change_tail(struct __sk_buff *s,__u32 n,__u64 flags)
{
    assert(!flags); assert(n<=sizeof(s->data));
    int error=fails();
    if(!error || mutate_on_error) {
        memset(s->data+s->len,0,n-s->len); s->len=n;
        if(s->state == CHECKSUM_COMPLETE) s->state=CHECKSUM_NONE;
    }
    return error?-1:0;
}
__s64 bpf_csum_diff(__be32 *from,__u32 fn,__be32 *to,__u32 tn,__u32 seed)
{
    assert(fn%4==0 && tn%4==0 && ((uintptr_t)from%4)==0 && ((uintptr_t)to%4)==0);
    if(fails()) return -1;
    uint64_t n=seed; uint16_t word;
    for(unsigned i=0;i<fn;i+=2) { memcpy(&word,(uint8_t*)from+i,2); n+=(uint16_t)~word; }
    for(unsigned i=0;i<tn;i+=2) { memcpy(&word,(uint8_t*)to+i,2); n+=word; }
    return fold(n);
}
static void replace(struct __sk_buff *s, unsigned off,uint64_t from,uint64_t to,uint64_t flags,int layer4)
{
    uint16_t value; memcpy(&value,s->data+off,2);
    uint64_t diff;
    assert((flags & 15)==0 || (flags & 15)==2);
    if((flags & 15)==2) diff=(uint16_t)~from+(uint64_t)(uint16_t)to;
    else { assert(from==0); diff=to; }
    if(layer4 && s->state==CHECKSUM_PARTIAL) {
        if(!(flags & BPF_F_PSEUDO_HDR)) return;
        value=fold(value+diff);
    } else value=(uint16_t)~fold((uint16_t)~value+diff);
    memcpy(s->data+off,&value,2);
}
int bpf_l4_csum_replace(struct __sk_buff *s,__u32 off,__u64 from,__u64 to,__u64 flags)
{ int error=fails(); if(!error || mutate_on_error) replace(s,off,from,to,flags,1); return error?-1:0; }
int bpf_l3_csum_replace(struct __sk_buff *s,__u32 off,__u64 from,__u64 to,__u64 flags)
{ int error=fails(); if(!error || mutate_on_error) replace(s,off,from,to,flags,0); return error?-1:0; }
static void reset(void) { calls=0; fail_at=0; mutate_on_error=0; memset(host_stats,0,sizeof(host_stats)); }
static struct __sk_buff packet(int ios,int state)
{
    struct __sk_buff s={0}; s.len=ios?74:66; s.state=state;
    for(unsigned i=0;i<s.len;i++) s.data[i]=random32();
    s.data[12]=8; s.data[13]=0; s.data[14]=0x45;
    put_be(s.data+16,s.len-14); put_be(s.data+20,0x4000);
    s.data[23]=6; put_be(s.data+24,0);
    put_be(s.data+24,(uint16_t)~fold(sum_be(s.data+14,20)));
    s.data[46]=(ios?0xa0:0x80)|(random32()&15);
    s.data[47]=2|(random32()&0xc0); put_be(s.data+50,0);
    uint8_t *p=s.data+54; p[0]=2; p[1]=4;
    if(ios) { p[4]=4; p[5]=2; p[6]=8; p[7]=10; p[16]=1; p[17]=3; p[18]=3; p[19]%=15; }
    else { p[4]=1; p[5]=1; p[6]=4; p[7]=2; p[8]=1; p[9]=3; p[10]=3; p[11]%=15; }
    put_be(s.data+50,state==CHECKSUM_PARTIAL?pseudo(&s):(uint16_t)~fold(pseudo(&s)+sum_be(s.data+34,s.len-34)));
    s.complete_sum=fold(sum_be(s.data,s.len));
    return s;
}
static void valid_case(int ios,int state,int marked)
{
    reset(); struct __sk_buff before=packet(ios,state), s=before;
    s.mark=ios?MARK_IOS:MARK_WIN;
    assert((marked?prog_mark(&s):ios?prog_ios(&s):prog_win(&s))==TC_ACT_OK);
    assert(host_stats[ios?ST_IOS_OK:ST_WIN_OK]==1 && host_stats[ST_DROP]==0);
    assert(s.len==before.len+(ios?4:0));
    assert(s.state==(ios&&state==CHECKSUM_COMPLETE?CHECKSUM_NONE:state));
    /* Every byte outside options, doff, lengths and checksums is immutable. */
    for(unsigned i=0;i<54;i++)
        if(!(ios && (i==16||i==17||i==24||i==25||i==46||i==50||i==51))) assert(s.data[i]==before.data[i]);
    uint8_t expected[24]; memcpy(expected,before.data+54,4);
    if(ios) {
        memcpy(expected+4,before.data+70,4); expected[8]=1; expected[9]=1;
        memcpy(expected+10,before.data+60,10); expected[20]=4; expected[21]=2; expected[22]=0; expected[23]=0;
    } else {
        memcpy(expected+4,before.data+62,4); memcpy(expected+8,before.data+58,4);
        assert(s.complete_sum==before.complete_sum);
    }
    assert(!memcmp(expected,s.data+54,ios?24:12));
    assert(fold(sum_be(s.data+14,20))==65535);
    if(state==CHECKSUM_PARTIAL) assert(read_be(s.data+50)==pseudo(&s));
    complete(&s); assert(wire_valid(&s)); cases++;
}
static void failures(int ios)
{
    for(int state=0;state<4;state++) {
        reset(); struct __sk_buff before=packet(ios,state), s=before;
        assert((ios?prog_ios(&s):prog_win(&s))==TC_ACT_OK);
        unsigned total=calls, first_mutation=ios?7:5;
        assert(total==(ios?14u:5u));
        for(unsigned f=1;f<=total;f++) for(int dirty=0;dirty<2;dirty++) {
            reset(); fail_at=f; mutate_on_error=dirty; s=before;
            int result=ios?prog_ios(&s):prog_win(&s);
            if(f<first_mutation) { assert(result==TC_ACT_OK); assert(!memcmp(&s,&before,sizeof(s))); }
            else { assert(result==TC_ACT_SHOT); assert(host_stats[ST_DROP]==1); }
            cases++;
        }
    }
    reset();
}
static void skip_cases(int ios)
{
    for(unsigned k=0;k<23;k++) {
        reset(); struct __sk_buff s=packet(ios,CHECKSUM_PARTIAL);
        switch(k) {
        case 0:s.data[12]=0x86;s.data[13]=0xdd;break; /* IPv6 */
        case 1:s.data[12]=0x81;s.data[13]=0;break; /* VLAN */
        case 2:s.data[14]=0x46;break; /* IP options */
        case 3:s.data[23]=17;break;
        case 4:s.data[20]|=0x20;break; /* MF */
        case 5:s.data[21]=1;break; /* fragment offset */
        case 6:s.data[20]|=0x80;break; /* reserved */
        case 7:s.data[47]|=0x10;break; /* SYNACK */
        case 8:s.data[47]|=4;break; /* SYN RST */
        case 9:s.data[47]|=1;break;
        case 10:s.data[47]|=8;break;
        case 11:s.data[47]|=0x20;break;
        case 12:s.data[47]=0x10;break;
        case 13:s.len++;put_be(s.data+16,s.len-14);break; /* TFO payload */
        case 14:s.len++;break; /* Ethernet padding */
        case 15:s.data[46]=0x40;break;
        case 16:s.data[46]=0xf0;break;
        case 17:s.data[55]=3;break; /* unknown layout */
        case 18:s.len=30;break;
        case 19:put_be(s.data+16,39);break;
        case 20:s.data[46]=0x50;put_be(s.data+16,40);s.len=54;break;
        case 21:s.data[14]=0x65;break;
        case 22:s.data[54]=30;break; /* unknown kind */
        }
        struct __sk_buff before=s;
        assert((ios?prog_ios(&s):prog_win(&s))==TC_ACT_OK);
        assert(!memcmp(&s,&before,sizeof(s))); assert(!host_stats[ST_DROP]); cases++;
    }
    reset(); struct __sk_buff s=packet(ios,3);s.mark=0x99;struct __sk_buff before=s;
    assert(prog_mark(&s)==TC_ACT_OK && !calls && !memcmp(&s,&before,sizeof(s))); cases++;
}

static void captured_ios_regression(void)
{
    /* Supplied phase B packet #181, after the original broken rewrite. */
    const char *hex="ae96afa1abc6aed72dc27084080045000040a664400040067fae0a5100030a510001b3661f9087b58a8c00000000b002ffff85330000020405b4010303060101080a724d459d0000000004020000";
    struct __sk_buff captured={0}; captured.len=78;
    for(unsigned i=0;i<78;i++) { unsigned x; assert(sscanf(hex+2*i,"%2x",&x)==1);captured.data[i]=(uint8_t)x; }
    assert(wire_valid(&captured));
    captured.state=CHECKSUM_PARTIAL; struct __sk_buff broken=captured;
    complete(&broken);assert(read_be(broken.data+50)==0x14d8);assert(!wire_valid(&broken));
    for(int state=0;state<4;state++) {
        reset();struct __sk_buff s=captured;s.len=74;s.state=state;
        s.data[46]=0xa0;put_be(s.data+16,60);put_be(s.data+24,0);
        put_be(s.data+24,(uint16_t)~fold(sum_be(s.data+14,20)));
        uint8_t *p=s.data+54; p[4]=4;p[5]=2;
        memcpy(p+6,captured.data+64,10);memcpy(p+16,captured.data+58,4);
        put_be(s.data+50,0);
        put_be(s.data+50,state==CHECKSUM_PARTIAL?pseudo(&s):(uint16_t)~fold(pseudo(&s)+sum_be(s.data+34,40)));
        assert(prog_ios(&s)==TC_ACT_OK);
        assert(read_be(s.data+50)==(state==CHECKSUM_PARTIAL?0x14d8:0x8533));
        complete(&s);assert(wire_valid(&s));assert(!memcmp(s.data,captured.data,78));cases++;
    }
}

int main(void)
{
    captured_ios_regression();
    for(int ios=0;ios<2;ios++) {
        for(int state=0;state<4;state++) for(int i=0;i<4096;i++) valid_case(ios,state,i&1);
        failures(ios); skip_cases(ios);
    }
    printf("PASS: %u actual-source cases; 4 checksum states; randomized fields; 19 helper failure positions x 4 states x 2 failure modes; unsupported/marked traffic\n",cases);
    return 0;
}
