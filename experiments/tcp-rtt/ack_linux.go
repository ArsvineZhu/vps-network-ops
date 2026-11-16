package main

import (
	"context"
	"encoding/binary"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	nfqueue "github.com/florianl/go-nfqueue/v2"
	"golang.org/x/sys/unix"
)

type flow struct {
	initial, remote, last uint32
	handshake             bool
}

// Only a dedicated experiment namespace may attach queue 9500.
func ackExperiment(policy string, delay time.Duration) {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	q, e := nfqueue.Open(&nfqueue.Config{NfQueue: 9500, AfFamily: unix.AF_INET, MaxPacketLen: 65535, MaxQueueLen: 4096, Copymode: nfqueue.NfQnlCopyPacket, WriteTimeout: time.Second})
	must(e)
	defer q.Close()
	must(q.Con.SetReadBuffer(8 * 1024 * 1024))
	flows := map[string]flow{}
	errors := make(chan error, 1)
	fail := func(e error) int {
		select {
		case errors <- e:
		default:
		}
		stop()
		return 1
	}
	e = q.RegisterWithErrorFunc(ctx, func(a nfqueue.Attribute) int {
		if a.PacketID == nil {
			return fail(fmt.Errorf("missing packet ID"))
		}
		id := *a.PacketID
		hold := false
		if a.Payload != nil {
			p := *a.Payload
			if len(p) >= 40 && p[0]>>4 == 4 && p[9] == 6 && binary.BigEndian.Uint16(p[6:8])&0x3fff == 0 {
				ih := int(p[0]&15) * 4
				total := int(binary.BigEndian.Uint16(p[2:4]))
				if ih >= 20 && total <= len(p) && total >= ih+20 {
					t := p[ih:total]
					th := int(t[12]>>4) * 4
					if th >= 20 && th <= len(t) {
						key := string(p[12:20]) + string(t[:4])
						inbound := binary.BigEndian.Uint16(t[:2]) == 4433
						if inbound {
							key = string(p[16:20]) + string(p[12:16]) + string(t[2:4]) + string(t[:2])
						}
						flags := t[13]
						seq := binary.BigEndian.Uint32(t[4:8])
						ack := binary.BigEndian.Uint32(t[8:12])
						f, ok := flows[key]
						if flags&0x12 == 2 {
							f = flow{initial: seq}
							flows[key] = f
							ok = true
						}
						if inbound && flags&0x12 == 0x12 && ok && ack == f.initial+1 {
							f.remote = seq
							flows[key] = f
						}
						sack := false
						for off := 20; off < th; {
							kind := t[off]
							if kind == 0 {
								break
							}
							if kind == 1 {
								off++
								continue
							}
							if off+1 >= th || t[off+1] < 2 || off+int(t[off+1]) > th {
								sack = true
								break
							}
							if kind == 5 {
								sack = true
							}
							off += int(t[off+1])
						}
						if !inbound && ok && flags == 0x10 && th == len(t) && !sack {
							if !f.handshake && seq == f.initial+1 && ack == f.remote+1 {
								hold = policy == "handshake"
								f.handshake = true
							} else if f.handshake && int32(ack-f.last) > 0 {
								hold = policy == "data"
							}
							f.last = ack
							flows[key] = f
						}
						if !inbound && ok && flags&0x10 != 0 && int32(ack-f.last) > 0 {
							f.last = ack
							flows[key] = f
						}
						if flags&5 != 0 {
							delete(flows, key)
						}
					}
				}
			}
		}
		if hold {
			event(map[string]any{"phase": "ack_queued", "packet": id, "delay_ns": delay.Nanoseconds()})
			time.AfterFunc(delay, func() {
				if err := q.SetVerdict(id, nfqueue.NfAccept); err != nil {
					fail(err)
				}
			})
			return 0
		}
		if e := q.SetVerdict(id, nfqueue.NfAccept); e != nil {
			return fail(e)
		}
		return 0
	}, func(e error) int { return fail(e) })
	must(e)
	event(map[string]any{"phase": "queue_ready"})
	<-ctx.Done()
	select {
	case e := <-errors:
		must(e)
	default:
	}
}
