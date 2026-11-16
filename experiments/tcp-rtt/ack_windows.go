package main

import (
	"fmt"
	"time"
)

func ackExperiment(_ string, _ time.Duration) { must(fmt.Errorf("ACK experiments require Linux")) }
