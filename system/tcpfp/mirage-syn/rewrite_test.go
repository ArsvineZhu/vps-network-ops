package syn

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"math/rand"
	"os"
	"path/filepath"
	"testing"
)

const nativeHex = "4500003cabb8400040067b010a0000010a0000029c4000501234567800000000a002ff282bba00000204058c0402080a010203040000000001030307"

func fixture(t testing.TB, profile Profile) []byte {
	t.Helper()
	p, err := hex.DecodeString(nativeHex)
	if err != nil {
		t.Fatal(err)
	}
	if profile.Name == "windows" {
		p = append(append([]byte{}, p[:44]...), []byte{1, 1, 4, 2, 1, 3, 3, 7}...)
		binary.BigEndian.PutUint16(p[2:4], uint16(len(p)))
		p[32] = byte((len(p)-20)/4) << 4
	}
	return p
}

func validSum(data []byte) bool {
	var sum uint32
	for i := 0; i < len(data); i += 2 {
		sum += uint32(data[i]) << 8
		if i+1 < len(data) {
			sum += uint32(data[i+1])
		}
	}
	for sum > 65535 {
		sum = (sum & 65535) + (sum >> 16)
	}
	return sum == 65535
}

func assertChecksums(t testing.TB, p []byte) {
	t.Helper()
	if !validSum(p[:20]) {
		t.Fatal("invalid IP checksum")
	}
	ps := append([]byte{}, p[12:20]...)
	ps = append(ps, 0, 6, byte((len(p)-20)>>8), byte(len(p)-20))
	ps = append(ps, p[20:]...)
	if !validSum(ps) {
		t.Fatal("invalid TCP checksum")
	}
}

func TestProfiles(t *testing.T) {
	for _, profile := range []Profile{Windows(), IOS()} {
		t.Run(profile.Name, func(t *testing.T) {
			for seed := int64(0); seed < 128; seed++ {
				p := fixture(t, profile)
				rng := rand.New(rand.NewSource(seed))
				for _, i := range []int{1, 4, 5, 8, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 34, 35, 38, 39, 42, 43} {
					p[i] = byte(rng.Intn(256))
				}
				p[32] |= byte(rng.Intn(16))
				p[33] |= byte(rng.Intn(4)) << 6
				if profile.Name == "ios" {
					for i := 48; i < 56; i++ {
						p[i] = byte(rng.Intn(256))
					}
				}
				p[len(p)-1] = byte(rng.Intn(15))
				saved := append([]byte{}, p...)
				out, changed, _, err := rewrite(p, profile)
				if err != nil || !changed {
					t.Fatalf("changed=%v err=%v", changed, err)
				}
				if !bytes.Equal(p, saved) {
					t.Fatal("mutated input")
				}
				for i := 0; i < 40; i++ {
					if i != 2 && i != 3 && i != 10 && i != 11 && i != 32 && i != 36 && i != 37 && out[i] != p[i] {
						t.Fatalf("header byte %d changed", i)
					}
				}
				if out[32]&15 != p[32]&15 {
					t.Fatal("TCP reserved bits changed")
				}
				expected := append([]byte{}, p[40:44]...)
				expected = append(expected, 1, 3, 3, p[len(p)-1], 1, 1)
				if profile.Name == "ios" {
					expected = append(expected, p[46:56]...)
				}
				expected = append(expected, 4, 2)
				if profile.Name == "ios" {
					expected = append(expected, 0, 0)
				}
				if !bytes.Equal(out[40:], expected) || len(out) != 40+len(expected) || int(out[32]>>4)*4 != 20+len(expected) || int(binary.BigEndian.Uint16(out[2:4])) != len(out) {
					t.Fatalf("bad option layout: %x", out[40:])
				}
				assertChecksums(t, out)
				out2, changed2, _, err := rewrite(p, profile)
				if err != nil || !changed2 || !bytes.Equal(out, out2) {
					t.Fatal("retransmission differs")
				}
				again, changed, _, err := rewrite(out, profile)
				if err != nil || changed || !bytes.Equal(again, out) {
					t.Fatal("rewrite is not idempotent")
				}
			}
		})
	}
}

func TestPassThrough(t *testing.T) {
	for name, mutate := range map[string]func([]byte) []byte{
		"fin":          func(p []byte) []byte { p[33] |= 1; return p },
		"rst":          func(p []byte) []byte { p[33] |= 4; return p },
		"psh":          func(p []byte) []byte { p[33] |= 8; return p },
		"ack":          func(p []byte) []byte { p[33] |= 16; return p },
		"urg":          func(p []byte) []byte { p[33] |= 32; return p },
		"reserved":     func(p []byte) []byte { p[6] |= 128; return p },
		"fragment":     func(p []byte) []byte { p[6] |= 32; return p },
		"offset":       func(p []byte) []byte { p[7] = 1; return p },
		"unknown":      func(p []byte) []byte { p[40] = 30; return p },
		"missing":      func(p []byte) []byte { copy(p[57:60], []byte{1, 1, 1}); return p },
		"duplicate":    func(p []byte) []byte { copy(p[40:44], []byte{3, 3, 7, 1}); return p },
		"payload":      func(p []byte) []byte { p = append(p, 65); p[3]++; return p },
		"ipv6":         func(p []byte) []byte { p[0] = 0x60; return p },
		"ip options":   func(p []byte) []byte { p[0] = 0x46; return p },
		"non tcp":      func(p []byte) []byte { p[9] = 17; return p },
		"missing mss":  func(p []byte) []byte { copy(p[40:44], []byte{1, 1, 1, 1}); return p },
		"missing sack": func(p []byte) []byte { copy(p[44:46], []byte{1, 1}); return p },
		"missing timestamp": func(p []byte) []byte {
			for i := 46; i < 56; i++ {
				p[i] = 1
			}
			return p
		},
	} {
		t.Run(name, func(t *testing.T) {
			p := mutate(fixture(t, IOS()))
			saved := append([]byte{}, p...)
			out, changed, _, err := rewrite(p, IOS())
			if changed || err != nil || !bytes.Equal(out, saved) || !bytes.Equal(p, saved) {
				t.Fatalf("changed=%v err=%v", changed, err)
			}
		})
	}
}

func TestMalformedAndConfiguration(t *testing.T) {
	for _, p := range [][]byte{nil, {0x45}, fixture(t, IOS())[:30]} {
		out, changed, _, err := rewrite(p, IOS())
		if err == nil || changed || !bytes.Equal(out, p) {
			t.Fatal("malformed packet accepted")
		}
	}
	path := filepath.Join(t.TempDir(), "config.yaml")
	config := "interface: e0\nsyn:\n  enabled: true\n  queue_num: 4949\n  profile: ios\n  failure_mode: open\n  status_interval: 30s\n"
	if err := os.WriteFile(path, []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := LoadConfig(path)
	if err != nil || c.SYN.Profile != "ios" || c.SYN.FailureMode != "open" || c.SYN.QueueNum != 4949 {
		t.Fatalf("%+v %v", c, err)
	}
	if err := os.WriteFile(path, []byte("syn:\n  unknown: true\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfig(path); err == nil {
		t.Fatal("unknown setting accepted")
	}
}

func TestOptionBoundaries(t *testing.T) {
	for _, mutate := range []func([]byte){
		func(p []byte) { p[41] = 3 },
		func(p []byte) { p[59] = 15 },
		func(p []byte) { p[32] = 0xf0 },
		func(p []byte) { p[3]++ },
	} {
		p := fixture(t, IOS())
		mutate(p)
		out, changed, _, err := rewrite(p, IOS())
		if err == nil || changed || !bytes.Equal(p, out) {
			t.Fatal("invalid packet was rewritten")
		}
	}
	p := fixture(t, IOS())
	if out, changed, _, err := rewrite(p, Windows()); err != nil || changed || !bytes.Equal(out, p) {
		t.Fatal("Windows accepted timestamp option")
	}
	// The same supported options in another order with EOL padding remain valid.
	p = fixture(t, IOS())
	options := append([]byte{}, p[46:56]...)
	options = append(options, p[40:46]...)
	options = append(options, p[57:60]...)
	options = append(options, 0)
	copy(p[40:], options)
	out, changed, _, err := rewrite(p, IOS())
	if err != nil || !changed {
		t.Fatalf("reordered options: %v %v", changed, err)
	}
	assertChecksums(t, out)
}

func FuzzRewrite(f *testing.F) {
	f.Add(fixture(f, IOS()))
	f.Add(fixture(f, Windows()))
	f.Fuzz(func(t *testing.T, in []byte) {
		for _, p := range []Profile{Windows(), IOS()} {
			saved := append([]byte{}, in...)
			out, changed, _, err := rewrite(in, p)
			if !bytes.Equal(saved, in) {
				t.Fatal("mutated input")
			}
			if changed {
				if err != nil || len(out) < 40 {
					t.Fatal("bad rewrite")
				}
				assertChecksums(t, out)
			} else if !bytes.Equal(out, in) {
				t.Fatal("modified pass-through")
			}
		}
	})
}
