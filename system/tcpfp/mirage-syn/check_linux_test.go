//go:build linux

package syn

import "testing"

func TestQueueStatus(t *testing.T) {
	q, err := parseQueueStatus(" 4949 100 3 2 65531 4 5 9 1\n", 4949)
	if err != nil || q != (queueInfo{3, 4, 5}) {
		t.Fatalf("%+v %v", q, err)
	}
	for _, input := range []string{"", "4949 3", "4949 100 3 2 65531 X 5 9 1"} {
		if _, err := parseQueueStatus(input, 4949); err == nil {
			t.Fatal(input)
		}
	}
}
