//go:build linux

package syn

import (
	"context"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"strings"
)

type queueInfo struct{ Pending, Dropped, UserDropped uint64 }

func parseQueueStatus(s string, id uint16) (queueInfo, error) {
	for _, line := range strings.Split(s, "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		queue, err := strconv.ParseUint(fields[0], 10, 16)
		if err != nil {
			return queueInfo{}, fmt.Errorf("invalid queue entry: %w", err)
		}
		if queue != uint64(id) {
			continue
		}
		if len(fields) < 8 {
			return queueInfo{}, fmt.Errorf("incomplete queue entry")
		}
		values := make([]uint64, 3)
		for i, pos := range []int{2, 5, 6} {
			values[i], err = strconv.ParseUint(fields[pos], 10, 64)
			if err != nil {
				return queueInfo{}, fmt.Errorf("invalid queue counter: %w", err)
			}
		}
		return queueInfo{values[0], values[1], values[2]}, nil
	}
	return queueInfo{}, fmt.Errorf("queue %d not found", id)
}

func queueStatus(id uint16) (queueInfo, error) {
	b, err := os.ReadFile("/proc/net/netfilter/nfnetlink_queue")
	if err != nil {
		return queueInfo{}, err
	}
	return parseQueueStatus(string(b), id)
}

func Check(ctx context.Context, c Config, w io.Writer) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := c.Validate(); err != nil {
		return err
	}
	if _, err := net.InterfaceByName(c.Interface); err != nil {
		return err
	}
	expected := map[string]string{"tcp_sack": "1", "tcp_window_scaling": "1", "tcp_timestamps": "0", "ip_default_ttl": "129"}
	if c.SYN.Profile == "ios" {
		expected["tcp_timestamps"] = "1"
		expected["ip_default_ttl"] = "65"
	}
	for key, want := range expected {
		data, err := os.ReadFile("/proc/sys/net/ipv4/" + key)
		if err != nil {
			return err
		}
		if got := strings.TrimSpace(string(data)); got != want {
			return fmt.Errorf("%s: got %s, expected %s", key, got, want)
		}
	}
	q, err := queueStatus(c.SYN.QueueNum)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(w, "queue=%d pending=%d dropped=%d user_dropped=%d\n", c.SYN.QueueNum, q.Pending, q.Dropped, q.UserDropped)
	return err
}
