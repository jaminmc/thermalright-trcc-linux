# Build on macOS only: make && sudo cp trcc-powermetrics-helper /Library/PrivilegedHelperTools/
CFLAGS ?= -O2 -Wall -Wextra

trcc-powermetrics-helper: main.c
	$(CC) $(CFLAGS) -o $@ main.c

clean:
	rm -f trcc-powermetrics-helper

.PHONY: clean
