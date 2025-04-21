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
import threading
import select
import termios
import tty
from collections import deque
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
    def __init__(self):
        # dynamic list of nodes (populated via 'initialized' events)
        self.nodes = []
        # unlimited history of events per node: deque of (ts, typ, other)
        self.events = {}
        # connectivity matrix: for each dst, set of src nodes that can reach it
        self.connectivity = {}
        # latest state snapshot per node
        # { node: { 'uptime': str, 'entries': [(name,ts,lat,lon), ...] } }
        self.states = {}
        # view mode: 'events' or 'state'
        self.mode = 'events'

    def add_node(self, name):
        if name in self.nodes:
            return
        self.nodes.append(name)
        self.events[name] = deque()
        self.connectivity[name] = set()
        self.states[name] = None

    def parse_line(self, line):
        parts = line.split(',', 2)
        if len(parts) < 2:
            return
        ts_s, ev = parts[0], parts[1]
        try:
            ts = float(ts_s)
        except ValueError:
            return
        # handle node initialization
        if ev == 'initialized':  # format: ts,initialized,NODx
            name = parts[2]
            self.add_node(name)
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
            # record tx event (no destination, just mark TX)
            self.events[src].append((ts, 'TX', 'TX'))
        elif ev == 'forward':
            # format: ts,forward,src,dst,HEXDATA
            fields = parts[2].split(',', 2)
            if len(fields) < 2:
                return
            src, dst = fields[0], fields[1]
            # record receive event only; source TX is already captured by 'tx'
            self.events[dst].append((ts, 'RX', src))
        elif ev == 'state':
            # format: ts,state,dst,get_state,<uptime_ms>,<NAME1>,<TS1>,<LAT1>,<LON1>,...
            rest = parts[2].split(',', 1)
            if len(rest) < 2:
                return
            dst, state_str = rest
            sp = state_str.split(',')
            if not sp or sp[0] != 'get_state':
                return
            uptime = sp[1]
            entries = sp[2:]
            node_list = []
            for i in range(len(entries) // 4):
                name_i, ts_i, lat_i, lon_i = entries[4*i:4*i+4]
                node_list.append((name_i, ts_i, lat_i, lon_i))
            self.states[dst] = {'uptime': uptime, 'entries': node_list}

    def generate_view(self):
        # choose view based on mode
        if self.mode == 'state':
            return self.generate_state_view()
        panels = []
        # always display nodes in sorted order
        for n in sorted(self.nodes):
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

    def generate_state_view(self):
        panels = []
        # always display nodes in sorted order
        for n in sorted(self.nodes):
            text = Text()
            st = self.states.get(n)
            if st:
                text.append(f"Uptime: {st['uptime']} ms\n", style="green")
                peers = sorted(self.connectivity.get(n, []))
                peers_str = ", ".join(peers) if peers else "<none>"
                text.append(f"Peers in: {peers_str}\n", style="cyan")
                text.append("Entries:\n", style="magenta")
                for name_i, ts_i, lat_i, lon_i in st['entries']:
                    text.append(f" {name_i}: ts={ts_i}, lat={lat_i}, lon={lon_i}\n")
            else:
                text.append("No state yet\n", style="red")
            panels.append(Panel(text, title=n, expand=True))
        return Columns(panels)

def main():
    parser = argparse.ArgumentParser(description="Live monitor for sim_output.log")
    parser.add_argument('--log', default='sim_output.log',
                        help='Path to sim_output.log file, or - to read from stdin')
    parser.add_argument('--mode', choices=['events','state'], default='events',
                        help='Select display mode: events or state')
    args = parser.parse_args()

    # Determine input source and escape support
    if args.log == '-':
        lines = (line.rstrip("\n") for line in sys.stdin)
        use_escape = False
    else:
        while not os.path.exists(args.log):
            time.sleep(0.1)
        lines = tail_f(args.log)
        use_escape = sys.stdin.isatty()

    # Setup ESC listener to exit
    stop_event = threading.Event()
    if use_escape:
        fd = sys.stdin.fileno()
        orig_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        def esc_listener():
            while not stop_event.is_set():
                dr, _, _ = select.select([sys.stdin], [], [], 0.1)
                if dr and sys.stdin.read(1) == '\x1b':
                    stop_event.set()
        threading.Thread(target=esc_listener, daemon=True).start()

    mon = Monitor()
    mon.mode = args.mode
    try:
        with Live(mon.generate_view(), refresh_per_second=4, screen=True) as live:
            for line in lines:
                if use_escape and stop_event.is_set():
                    break
                if not line:
                    continue
                mon.parse_line(line)
                live.update(mon.generate_view())
    except KeyboardInterrupt:
        pass
    finally:
        if use_escape:
            termios.tcsetattr(fd, termios.TCSADRAIN, orig_settings)

if __name__ == '__main__':
    main()