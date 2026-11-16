package main

import (
	"encoding/binary"
	"net"
	"syscall"

	"golang.org/x/sys/windows"
)

func bindInterface(dialer *net.Dialer, index int) error {
	if index == 0 {
		return nil
	}
	if _, err := net.InterfaceByIndex(index); err != nil {
		return err
	}
	dialer.Control = func(_, _ string, raw syscall.RawConn) error {
		var result error
		err := raw.Control(func(fd uintptr) {
			var value [4]byte
			binary.BigEndian.PutUint32(value[:], uint32(index))
			// IP_UNICAST_IF takes an interface index in network byte order.
			result = windows.SetsockoptInet4Addr(windows.Handle(fd), windows.IPPROTO_IP, 31, value)
		})
		if err != nil {
			return err
		}
		return result
	}
	return nil
}
