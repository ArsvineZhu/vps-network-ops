package main

import (
	"net"
	"syscall"

	"golang.org/x/sys/unix"
)

func bindInterface(dialer *net.Dialer, index int) error {
	if index == 0 {
		return nil
	}
	nic, err := net.InterfaceByIndex(index)
	if err != nil {
		return err
	}
	dialer.Control = func(_, _ string, raw syscall.RawConn) error {
		var result error
		err := raw.Control(func(fd uintptr) {
			result = unix.SetsockoptString(int(fd), unix.SOL_SOCKET, unix.SO_BINDTODEVICE, nic.Name)
		})
		if err != nil {
			return err
		}
		return result
	}
	return nil
}
