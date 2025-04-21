#!/usr/bin/env python3
"""
monitor.py: Live ASCII visualization of network simulation events using Rich.

Reads sim_output.log (produced by sim.py via Tee) and displays a live 4-column view
showing, for each node:
  - Incoming connectivity (which nodes can reach it)
  - Last 5 packet events (TX/RX with timestamps)
"""
import os
import sys
import time
import argparse
from collections import deque

try:
    from rich.live import Live
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.text import Text
except ImportError:
    print("Error: please install rich (pip install rich)", file=sys.stderr)
    sys.exit(1)

def tail_f(path):
    with open(path, 'r') as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            yield line.rstrip("\n")

class Monitor:
    def __init__(self, nodes):
        self.nodes = list(nodes)
        # last 5 events per node: deque of (ts, typ, other)
        self.events = {n: deque(maxlen=5) for n in self.nodes}
        # connectivity matrix: for each dst, set of src nodes that can reach it
        self.connectivity = {n: set() for n in self.nodes}

    def parse_line(self, line):
        parts = line.split(',', 2)
        if len(parts) < 2:
            return
        ts_s, ev = parts[0], parts[1]
        try:
            ts = float(ts_s)
        except ValueError:
            return
        # events
        if ev == 'connectivity_update':
            matrix = parts[2]
            N = len(self.nodes)
            for i, src in enumerate(self.nodes):
                for j, dst in enumerate(self.nodes):
                    if matrix[i*N + j] == '1':
                        self.connectivity[dst].add(src)
                    else:
                        self.connectivity[dst].discard(src)
        elif ev == 'tx':
            # format: ts,tx,src,HEXDATA
            rest = parts[2]
            fields = rest.split(',', 1)
            if len(fields) < 1:
                return
            src = fields[0]
            # record tx event
            self.events[src].append((ts, 'TX', ''))
        elif ev == 'forward':
            # format: ts,forward,src,dst,HEXDATA
            fields = parts[2].split(',', 2)
            if len(fields) < 2:
                return
            src, dst = fields[0], fields[1]
            # record tx to dst and rx from src
            self.events[src].append((ts, 'TX', dst))
            self.events[dst].append((ts, 'RX', src))

    def generate_view(self):
        panels = []
        for n in self.nodes:
            text = Text()
            # connectivity
            peers = sorted(self.connectivity.get(n, []))
            peers_str = ", ".join(peers) if peers else "<none>"
            text.append(f"Peers in: {peers_str}\n", style="cyan")
            # last events
            text.append("Last events:\n", style="magenta")
            for ts, typ, other in list(self.events[n]):
                arrow = "→" if typ == 'TX' else "←"
                text.append(f" {ts:6.3f}s {arrow} {other}\n")
            panels.append(Panel(text, title=n, expand=True))
        return Columns(panels)

def main():
    parser = argparse.ArgumentParser(description="Live monitor for sim_output.log")
    parser.add_argument('--nodes', nargs='+', required=True,
                        help='List of node names (e.g. NOD1 NOD2)')
    parser.add_argument('--log', default='sim_output.log',
                        help='Path to sim_output.log file')
    args = parser.parse_args()

    # wait for log file
    while not os.path.exists(args.log):
        time.sleep(0.1)

    mon = Monitor(args.nodes)
    with Live(mon.generate_view(), refresh_per_second=4, screen=True) as live:
        for line in tail_f(args.log):
            mon.parse_line(line)
            live.update(mon.generate_view())

if __name__ == '__main__':
    main()