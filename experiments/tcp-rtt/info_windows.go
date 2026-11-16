package main

import "net"

func sample(_ *net.TCPConn, id, phase string) {
	event(map[string]any{"connection": id, "phase": phase, "error": "Server TCP_INFO requires Linux"})
}

func waitAcknowledged(_ *net.TCPConn, _ string) {}
