// Package syn normalizes IPv4 TCP SYN offers for outbound profiles.
package syn

import (
	"bytes"
	"encoding/binary"
	"fmt"
)

const (
	optionMSS  uint16 = 1 << 2
	optionWS   uint16 = 1 << 3
	optionSACK uint16 = 1 << 4
	optionTS   uint16 = 1 << 8
)

// Profile identifies one supported output layout and its required options.
type Profile struct {
	Name     string
	Required uint16
}

func Windows() Profile { return Profile{Name: "windows", Required: optionMSS | optionWS | optionSACK} }
func IOS() Profile {
	return Profile{Name: "ios", Required: optionMSS | optionWS | optionSACK | optionTS}
}

func (p Profile) validate() error {
	if p != Windows() && p != IOS() {
		return fmt.Errorf("unsupported SYN profile")
	}
	return nil
}

// Unsupported packets pass through unchanged; malformed packets report an error.
func rewrite(pkt []byte, p Profile) ([]byte, bool, string, error) {
	pass := func(reason string) ([]byte, bool, string, error) { return pkt, false, reason, nil }
	bad := func(reason string) ([]byte, bool, string, error) {
		return pkt, false, "malformed", fmt.Errorf("malformed packet: %s", reason)
	}
	if err := p.validate(); err != nil {
		return pkt, false, "profile", err
	}
	if len(pkt) == 0 {
		return bad("empty")
	}
	if pkt[0]>>4 != 4 {
		return pass("non_ipv4")
	}
	if len(pkt) < 20 || pkt[0]&15 < 5 {
		return bad("IPv4 header")
	}
	if pkt[9] != 6 {
		return pass("non_tcp")
	}
	if pkt[0]&15 != 5 {
		return pass("ip_options")
	}
	// DF is allowed; the reserved bit, MF and any fragment offset are not.
	if binary.BigEndian.Uint16(pkt[6:8])&0xbfff != 0 {
		return pass("fragment_or_reserved")
	}
	if int(binary.BigEndian.Uint16(pkt[2:4])) != len(pkt) || len(pkt) < 40 {
		return bad("IP length")
	}
	tcp := pkt[20:]
	// Keep ECN negotiation bits, but do not transform SYN+FIN/RST/PSH/ACK/URG.
	if tcp[13]&0x02 == 0 || tcp[13]&0x3d != 0 {
		return pass("non_initial_syn")
	}
	hlen := int(tcp[12]>>4) * 4
	if hlen < 20 || hlen > len(tcp) {
		return bad("TCP header length")
	}
	if hlen != len(tcp) {
		return pass("payload")
	}

	var seen uint16
	options := make(map[byte][]byte, 4)
	for remaining := tcp[20:hlen]; len(remaining) > 0; {
		kind := remaining[0]
		if kind == 1 {
			remaining = remaining[1:]
			continue
		}
		if kind == 0 {
			for _, padding := range remaining {
				if padding != 0 {
					return pass("unsupported_padding")
				}
			}
			break
		}
		var size int
		switch kind {
		case 2:
			size = 4
		case 3:
			size = 3
		case 4:
			size = 2
		case 8:
			size = 10
		default:
			return pass("unsupported_option")
		}
		if len(remaining) < size || int(remaining[1]) != size {
			return bad("option length")
		}
		mask := uint16(1) << kind
		if seen&mask != 0 {
			return pass("duplicate_option")
		}
		seen |= mask
		if kind == 3 && remaining[2] > 14 {
			return bad("window scale")
		}
		options[kind] = remaining[:size]
		remaining = remaining[size:]
	}
	if seen&p.Required != p.Required {
		return pass("missing_required_option")
	}
	allowed := p.Required
	if p.Name == "windows" {
		allowed |= optionTS
	}
	if seen & ^allowed != 0 {
		return pass("unsupported_option_set")
	}

	// Output option bytes are assembled from the original options; no value is
	// manufactured or altered. Windows declines timestamps before negotiation;
	// iOS retains the original timestamp offer and adds padding.
	var layout []byte
	layout = append(layout, options[2]...)
	layout = append(layout, 1)
	layout = append(layout, options[3]...)
	layout = append(layout, 1, 1)
	if p.Name == "ios" {
		layout = append(layout, options[8]...)
	}
	layout = append(layout, options[4]...)
	if p.Name == "ios" {
		layout = append(layout, 0, 0)
	}
	if len(layout)%4 != 0 {
		return pkt, false, "profile", fmt.Errorf("invalid profile layout")
	}
	out := make([]byte, 40+len(layout))
	copy(out[:40], pkt[:40])
	copy(out[40:], layout)
	binary.BigEndian.PutUint16(out[2:4], uint16(len(out)))
	out[32] = byte((20+len(layout))/4)<<4 | (tcp[12] & 0x0f)
	out[10], out[11], out[36], out[37] = 0, 0, 0, 0
	binary.BigEndian.PutUint16(out[10:12], checksum(out[:20]))
	var pseudo [12]byte
	copy(pseudo[:8], out[12:20])
	pseudo[9] = 6
	binary.BigEndian.PutUint16(pseudo[10:12], uint16(len(out)-20))
	binary.BigEndian.PutUint16(out[36:38], checksum(pseudo[:], out[20:]))
	if bytes.Equal(out, pkt) {
		return pkt, false, "already_profiled", nil
	}
	return out, true, "rewritten", nil
}

// checksum is used with even-sized IP, pseudo-header and TCP components.
func checksum(parts ...[]byte) uint16 {
	var sum uint32
	for _, data := range parts {
		for len(data) >= 2 {
			sum += uint32(binary.BigEndian.Uint16(data))
			data = data[2:]
		}
		if len(data) == 1 {
			sum += uint32(data[0]) << 8
		}
	}
	for sum>>16 != 0 {
		sum = (sum & 0xffff) + (sum >> 16)
	}
	return ^uint16(sum)
}
