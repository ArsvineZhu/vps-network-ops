//go:build linux

package syn

import (
	"context"
	"encoding/binary"
	"fmt"
	"log"
	"net"
	"os"
	"strings"
	"sync"
	"time"

	nfqueue "github.com/florianl/go-nfqueue/v2"
	"golang.org/x/sys/unix"
)

type counters struct {
	mu                                                      sync.Mutex
	total, rewritten, skipped, errors, queueErrors, partial uint64
	reasons                                                 map[string]uint64
}

func (c *counters) packet(reason string, changed, failed, partial bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.total++
	if changed {
		c.rewritten++
	} else {
		c.skipped++
	}
	if failed {
		c.errors++
	}
	if partial {
		c.partial++
	}
	c.reasons[reason]++
}

func (c *counters) queueError() { c.mu.Lock(); c.queueErrors++; c.mu.Unlock() }

func (c *counters) report() {
	c.mu.Lock()
	defer c.mu.Unlock()
	log.Printf("packets=%d rewritten=%d skipped=%d errors=%d queue_errors=%d partial_checksums=%d reasons=%v",
		c.total, c.rewritten, c.skipped, c.errors, c.queueErrors, c.partial, c.reasons)
}

func notifyReady() error {
	address := os.Getenv("NOTIFY_SOCKET")
	if address == "" {
		return nil
	}
	if strings.HasPrefix(address, "@") {
		address = "\x00" + address[1:]
	}
	connection, err := net.DialUnix("unixgram", nil, &net.UnixAddr{Name: address, Net: "unixgram"})
	if err != nil {
		return err
	}
	defer connection.Close()
	_, err = connection.Write([]byte("READY=1\nSTATUS=NFQUEUE listener ready"))
	return err
}

// Run only listens on an already-scoped queue. The deployment layer creates and
// owns capture rules after readiness, and removes them before normal shutdown.
func Run(ctx context.Context, cfg Config) (result error) {
	if err := cfg.Validate(); err != nil {
		return err
	}
	if !cfg.SYN.Enabled {
		return fmt.Errorf("syn.enabled is false")
	}
	profile, err := cfg.Profile()
	if err != nil {
		return err
	}
	interval, _ := time.ParseDuration(cfg.SYN.StatusInterval)
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	flags := uint32(nfqueue.NfQaCfgFlagGSO)
	if cfg.SYN.FailureMode == "open" {
		flags |= nfqueue.NfQaCfgFlagFailOpen
	}
	queue, err := nfqueue.Open(&nfqueue.Config{NfQueue: cfg.SYN.QueueNum, AfFamily: unix.AF_INET,
		MaxPacketLen: 65531, MaxQueueLen: 4096, Copymode: nfqueue.NfQnlCopyPacket,
		Flags: flags, WriteTimeout: time.Second})
	if err != nil {
		return err
	}
	stats := &counters{reasons: make(map[string]uint64)}
	defer func() {
		cancel()
		if err := queue.Close(); err != nil && result == nil {
			result = err
		}
		stats.report()
	}()
	errors := make(chan error, 1)
	fail := func(err error) int {
		stats.queueError()
		select {
		case errors <- err:
		default:
		}
		cancel()
		return 1
	}
	err = queue.RegisterWithErrorFunc(ctx, func(a nfqueue.Attribute) int {
		if a.PacketID == nil {
			return fail(fmt.Errorf("NFQUEUE message has no packet ID"))
		}
		partial := a.SkbInfo != nil && len(*a.SkbInfo) >= 4 && binary.BigEndian.Uint32(*a.SkbInfo)&1 != 0
		var output []byte
		var changed bool
		var rewriteErr error
		reason := "missing_payload"
		if a.Payload != nil && (a.CapLen == nil || int(*a.CapLen) == len(*a.Payload)) {
			output, changed, reason, rewriteErr = rewrite(*a.Payload, profile)
		} else if a.Payload != nil {
			reason = "truncated"
		}
		stats.packet(reason, changed, rewriteErr != nil, partial)
		var verdictErr error
		if changed {
			// nfqnl_mangle sets skb->ip_summed to CHECKSUM_NONE for a
			// replacement, including originally partial checksum packets.
			verdictErr = queue.SetVerdictWithOption(*a.PacketID, nfqueue.NfAccept, nfqueue.WithAlteredPacket(output))
		} else {
			verdictErr = queue.SetVerdict(*a.PacketID, nfqueue.NfAccept)
		}
		if verdictErr != nil {
			return fail(verdictErr)
		}
		return 0
	}, func(err error) int {
		if ctx.Err() != nil {
			return 1
		}
		return fail(err)
	})
	if err != nil {
		return err
	}
	if err := notifyReady(); err != nil {
		return fmt.Errorf("readiness notification: %w", err)
	}
	log.Printf("ready queue=%d interface=%s profile=%s failure_mode=%s", cfg.SYN.QueueNum, cfg.Interface, cfg.SYN.Profile, cfg.SYN.FailureMode)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			stats.report()
			if q, err := queueStatus(cfg.SYN.QueueNum); err == nil {
				log.Printf("kernel_queue=%d pending=%d dropped=%d user_dropped=%d", cfg.SYN.QueueNum, q.Pending, q.Dropped, q.UserDropped)
			} else {
				log.Printf("kernel_queue_status_error=%v", err)
			}
		case <-ctx.Done():
			select {
			case err := <-errors:
				return err
			default:
				return nil
			}
		}
	}
}
