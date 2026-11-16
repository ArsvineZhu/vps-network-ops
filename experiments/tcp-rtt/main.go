package main

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"flag"
	"fmt"
	"math/big"
	"net"
	"net/http"
	"net/http/httptrace"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"io"
)

var mu sync.Mutex
var origin = time.Now()

func event(v map[string]any) {
	mu.Lock()
	defer mu.Unlock()
	v["monotonic_ns"] = time.Since(origin).Nanoseconds()
	_ = json.NewEncoder(os.Stdout).Encode(v)
}

type connKey struct{}
type connection struct {
	tcp *net.TCPConn
	id  string
}
type listener struct{ net.Listener }

func (l listener) Accept() (net.Conn, error) {
	c, e := l.Listener.Accept()
	if e == nil {
		sample(c.(*net.TCPConn), c.RemoteAddr().String(), "accept")
	}
	return c, e
}
func certificate() (tls.Certificate, []byte) {
	k, e := rsa.GenerateKey(rand.Reader, 2048)
	must(e)
	serial, e := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 120))
	must(e)
	t := &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: "rtt.lab"}, DNSNames: []string{"rtt.lab"}, IPAddresses: []net.IP{net.ParseIP("10.231.2.2")}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(24 * time.Hour), KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, BasicConstraintsValid: true, IsCA: true}
	der, e := x509.CreateCertificate(rand.Reader, t, t, &k.PublicKey, k)
	must(e)
	cert := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	key := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(k)})
	pair, e := tls.X509KeyPair(cert, key)
	must(e)
	return pair, cert
}
func must(e error) {
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
func main() {
	mode := flag.String("mode", "client", "server, client, ack, or tcp")
	addr := flag.String("address", "10.231.2.2:4433", "listener or target")
	targetURL := flag.String("url", "", "external HTTPS measurement URL")
	ca := flag.String("ca", "ca.pem", "certificate path")
	connectAddress := flag.String("connect-address", "", "connect to this resolved address while retaining TLS hostname")
	nicIndex := flag.Int("interface-index", 0, "bind only probe sockets to this interface")
	proxy := flag.String("proxy", "", "HTTP CONNECT proxy URL")
	count := flag.Int("count", 30, "request count")
	size := flag.Int("size", 1024, "response bytes")
	preTLS := flag.Duration("pre-tls-delay", 0, "mechanism control: wait after TCP connect before TLS")
	fresh := flag.Bool("fresh", false, "disable connection reuse")
	h1 := flag.Bool("h1", false, "HTTP/1.1 only")
	policy := flag.String("ack-policy", "handshake", "handshake or data")
	delay := flag.Duration("delay", 0, "ACK delay")
	flag.Parse()
	if *mode == "ack" {
		if (*policy != "handshake" && *policy != "data") || *delay < 0 || *delay > time.Second {
			must(fmt.Errorf("invalid ACK policy or delay"))
		}
		ackExperiment(*policy, *delay)
		return
	}
	if *count < 1 || *size < 1 || *size > 4*1024*1024 {
		must(fmt.Errorf("invalid count or size"))
	}
	if *mode == "tcp" {
		d := &net.Dialer{Timeout: 5 * time.Second}
		must(bindInterface(d, *nicIndex))
		for i := 0; i < *count; i++ {
			start := time.Now()
			c, err := d.Dial("tcp4", *addr)
			v := map[string]any{"sample": i + 1, "connect_ns": time.Since(start).Nanoseconds(), "interface_index": *nicIndex}
			if err != nil {
				v["error"] = err.Error()
			} else {
				c.Close()
				v["success"] = true
			}
			event(v)
			time.Sleep(250 * time.Millisecond)
		}
		return
	}
	if *mode == "server" {
		pair, cert := certificate()
		must(os.WriteFile(*ca, cert, 0600))
		ln, e := net.Listen("tcp", *addr)
		must(e)
		srv := &http.Server{TLSConfig: &tls.Config{Certificates: []tls.Certificate{pair}}, ReadHeaderTimeout: 10 * time.Second, ConnContext: func(ctx context.Context, c net.Conn) context.Context {
			t := c.(*tls.Conn).NetConn().(*net.TCPConn)
			return context.WithValue(ctx, connKey{}, connection{t, t.RemoteAddr().String()})
		}, ConnState: func(c net.Conn, s http.ConnState) {
			if s == http.StateActive {
				t := c.(*tls.Conn).NetConn().(*net.TCPConn)
				sample(t, t.RemoteAddr().String(), "active_after_tls")
			}
		}}
		srv.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c := r.Context().Value(connKey{}).(connection)
			id := r.Header.Get("X-Request-ID")
			event(map[string]any{"connection": c.id, "request": id, "phase": "request", "protocol": r.Proto})
			sample(c.tcp, c.id, "request")
			n := *size
			if v := r.URL.Query().Get("size"); v != "" {
				_, _ = fmt.Sscanf(v, "%d", &n)
			}
			if n < 1 || n > 4*1024*1024 {
				http.Error(w, "invalid size", 400)
				return
			}
			w.Header().Set("Content-Length", fmt.Sprint(n))
			w.Header().Set("Cache-Control", "no-store")
			buf := make([]byte, 1024)
			firstWrite := true
			for n > 0 {
				part := min(n, len(buf))
				_, e := w.Write(buf[:part])
				if e != nil {
					return
				}
				n -= part
				if firstWrite {
					firstWrite = false
					_ = http.NewResponseController(w).Flush()
					sample(c.tcp, c.id, "first_write")
				}
			}
			_ = http.NewResponseController(w).Flush()
			sample(c.tcp, c.id, "write_complete")
			go waitAcknowledged(c.tcp, c.id)
		})
		must(srv.ServeTLS(listener{ln}, "", ""))
		return
	}
	if *mode != "client" {
		must(fmt.Errorf("unknown mode"))
	}
	var roots *x509.CertPool
	if *ca != "" {
		roots = x509.NewCertPool()
		b, e := os.ReadFile(*ca)
		must(e)
		if !roots.AppendCertsFromPEM(b) {
			must(fmt.Errorf("invalid CA"))
		}
	}
	tr := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots}, ForceAttemptHTTP2: !*h1, DisableKeepAlives: *fresh}
	if *proxy != "" {
		p, e := url.Parse(*proxy)
		must(e)
		tr.Proxy = http.ProxyURL(p)
	}
	if *preTLS < 0 || *preTLS > time.Second {
		must(fmt.Errorf("invalid pre-TLS delay"))
	}
	if *preTLS > 0 || *nicIndex > 0 || *connectAddress != "" {
		dialer := &net.Dialer{Timeout: 10 * time.Second}
		must(bindInterface(dialer, *nicIndex))
		tr.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
			if *connectAddress != "" {
				address = *connectAddress
			}
			conn, err := dialer.DialContext(ctx, network, address)
			if err != nil {
				return nil, err
			}
			timer := time.NewTimer(*preTLS)
			defer timer.Stop()
			select {
			case <-timer.C:
				return conn, nil
			case <-ctx.Done():
				conn.Close()
				return nil, ctx.Err()
			}
		}
	}
	client := &http.Client{Transport: tr, Timeout: 30 * time.Second}
	defer tr.CloseIdleConnections()
	for i := 0; i < *count; i++ {
		start := time.Now()
		id := fmt.Sprintf("%d-%d", start.UnixNano(), i)
		var first time.Duration
		var reused bool
		trace := &httptrace.ClientTrace{GotConn: func(g httptrace.GotConnInfo) { reused = g.Reused }, GotFirstResponseByte: func() { first = time.Since(start) }}
		requestURL := *targetURL
		if requestURL == "" {
			requestURL = "https://" + *addr + "/?size=" + fmt.Sprint(*size)
		}
		if !strings.HasPrefix(requestURL, "https://") {
			must(fmt.Errorf("HTTPS URL required"))
		}
		req, e := http.NewRequestWithContext(httptrace.WithClientTrace(context.Background(), trace), "GET", requestURL, nil)
		must(e)
		req.Header.Set("X-Request-ID", id)
		res, e := client.Do(req)
		v := map[string]any{"request": id, "reused": reused}
		if e != nil {
			v["error"] = e.Error()
		} else {
			body, e := io.ReadAll(io.LimitReader(res.Body, 4*1024*1024+1))
			n := int64(len(body))
			if *targetURL != "" {
				var observer any
				if json.Unmarshal(body, &observer) == nil {
					v["observer"] = observer
				}
			}
			v["body_bytes"] = n
			v["status"] = res.StatusCode
			v["protocol"] = res.Proto
			if e != nil {
				v["error"] = e.Error()
			}
			res.Body.Close()
		}
		v["total_ns"] = time.Since(start).Nanoseconds()
		v["ttfb_ns"] = first.Nanoseconds()
		event(v)
		time.Sleep(250 * time.Millisecond)
	}
}
