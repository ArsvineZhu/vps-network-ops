package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"runtime/debug"
	"syscall"

	syn "github.com/ArsvineZhu/vps-network-ops/system/tcpfp/mirage-syn"
)

func main() {
	if err := execute(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "mirage-syn:", err)
		os.Exit(1)
	}
}

func execute(args []string) error {
	if len(args) == 1 && args[0] == "version" {
		if info, ok := debug.ReadBuildInfo(); ok {
			fmt.Println("mirage-syn", info.GoVersion)
		} else {
			fmt.Println("mirage-syn")
		}
		return nil
	}
	if len(args) == 0 || (args[0] != "run" && args[0] != "check") {
		return fmt.Errorf("usage: mirage-syn run|check [-c config.yaml]")
	}
	command := args[0]
	f := flag.NewFlagSet(command, flag.ContinueOnError)
	path := f.String("c", "/etc/tcpfp/syn-windows.json", "YAML configuration")
	if err := f.Parse(args[1:]); err != nil {
		return err
	}
	if f.NArg() != 0 {
		return fmt.Errorf("unexpected arguments: %v", f.Args())
	}
	c, err := syn.LoadConfig(*path)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if command == "run" {
		return syn.Run(ctx, c)
	}
	return syn.Check(ctx, c, os.Stdout)
}
