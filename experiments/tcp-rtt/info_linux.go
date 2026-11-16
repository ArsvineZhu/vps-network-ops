package main

import (
	"net"
	"time"

	"golang.org/x/sys/unix"
)

func sample(c *net.TCPConn, id, phase string) {
	raw, e := c.SyscallConn()
	if e != nil {
		return
	}
	var info *unix.TCPInfo
	var err error
	e = raw.Control(func(fd uintptr) { info, err = unix.GetsockoptTCPInfo(int(fd), unix.IPPROTO_TCP, unix.TCP_INFO) })
	if e != nil || err != nil {
		event(map[string]any{"connection": id, "phase": phase, "error": "TCP_INFO unavailable"})
		return
	}
	event(map[string]any{"connection": id, "phase": phase, "tcp_info": info})
}

func waitAcknowledged(c *net.TCPConn, id string) {
	end := time.Now().Add(2 * time.Second)
	for time.Now().Before(end) {
		raw, e := c.SyscallConn()
		if e != nil {
			return
		}
		var info *unix.TCPInfo
		var err error
		e = raw.Control(func(fd uintptr) { info, err = unix.GetsockoptTCPInfo(int(fd), unix.IPPROTO_TCP, unix.TCP_INFO) })
		if e != nil || err != nil {
			return
		}
		if info.Unacked == 0 {
			sample(c, id, "after_ack")
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	sample(c, id, "ack_wait_timeout")
}
