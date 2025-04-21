#!./sim_venv/bin/python3
import os
import sys

# Auto re-exec using virtualenv python if not already
def _ensure_venv():
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.platform == 'win32':
        venv_py = os.path.join(here, 'sim_venv', 'Scripts', 'python.exe')
    else:
        venv_py = os.path.join(here, 'sim_venv', 'bin', 'python')
    if os.path.exists(venv_py):
        venv_py = os.path.abspath(venv_py)
        if os.path.abspath(sys.executable) != venv_py:
            os.execv(venv_py, [venv_py] + sys.argv)

_ensure_venv()
import random
"""
LoRa Network Simulator Orchestrator

This script reads a line-delimited, comma-separated input file of timed commands
(input.log), spawns one network_simulator instance per node, and orchestrates the
distribution of transmit_packet events according to a connectivity matrix.

Usage:
  sim.py [--input INPUT] [--nodes N1 N2 ...] [--node-exe EXE] [--outdir DIR] [--duration SECS]
"""
import argparse
import threading
import subprocess
import time
import os
import sys
import queue
import random
import select
import termios
import tty
from collections import deque
try:
    from rich.live import Live
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.text import Text
except ImportError:
    print("Error: please install rich (pip install rich)", file=sys.stderr)
    sys.exit(1)

# Tee stdout to both console and sim_output.log file
class Tee:
    def __init__(self, *writers):
        self.writers = writers
    def write(self, data):
        for w in self.writers:
            w.write(data)
    def flush(self):
        for w in self.writers:
            w.flush()

class NodeProc:
    def __init__(self, name, exe_path, outdir, start_time, dispatcher):
        self.name = name
        self.start_time = start_time
        self.dispatcher = dispatcher
        # Open log files
        self.stdout_log = open(os.path.join(outdir, f"{name}.stdout.log"), "w", buffering=1)
        self.stderr_log = open(os.path.join(outdir, f"{name}.stderr.log"), "w", buffering=1)
        # Launch process
        self.proc = subprocess.Popen(
            [exe_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )
        self._stdin_lock = threading.Lock()
        # Queue for capturing non-transmit stdout responses
        self._resp_queue = queue.Queue()
        # Start reader threads
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _timestamp(self):
        return time.time() - self.start_time

    def _read_stdout(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            ts = self._timestamp()
            # Log with timestamp
            self.stdout_log.write(f"{ts:.3f},{line}\n")
            # Intercept transmit_packet for forwarding
            if line.startswith("transmit_packet"):  # format: transmit_packet,LEN,HEXDATA
                try:
                    parts = line.split(',', 2)
                    hexdata = parts[2]
                except Exception:
                    continue
                # Log transmit event
                ts = self._timestamp()
                print(f"{ts:.3f},tx,{self.name},{hexdata}", flush=True)
                # Dispatch to other nodes
                self.dispatcher.deliver_packet(self.name, hexdata)
                # do not queue transmit_packet lines
                continue
            # Queue other stdout responses (e.g., node_update, get_state)
            self._resp_queue.put(line)

    def _read_stderr(self):
        for line in self.proc.stderr:
            line = line.rstrip("\n")
            ts = self._timestamp()
            self.stderr_log.write(f"{ts:.3f},{line}\n")

    def send_command(self, cmd_str):
        """
        Send a command line (without newline) to the node.
        """
        with self._stdin_lock:
            if self.proc.stdin:
                self.proc.stdin.write(cmd_str + "\n")
                self.proc.stdin.flush()

    def terminate(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
    def get_state(self, timeout=1.0):
        """
        Send a get_state command and wait for its response line.
        Returns the raw response (without timestamp) or None on timeout.
        """
        # send the get_state command
        with self._stdin_lock:
            if self.proc.stdin:
                self.proc.stdin.write("get_state\n")
                self.proc.stdin.flush()
        # clear any stale responses
        try:
            while True:
                self._resp_queue.get_nowait()
        except queue.Empty:
            pass
        # wait for get_state response
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                line = self._resp_queue.get(timeout=remaining)
            except queue.Empty:
                break
            if line.startswith("get_state"):
                return line
        return None

class Dispatcher:
    def __init__(self, node_names):
        # connectivity[src][dst] = bool
        self.node_names = list(node_names)
        self.N = len(self.node_names)
        self.conn = {src: {dst: False for dst in self.node_names} for src in self.node_names}
        self._lock = threading.Lock()
        self.nodes = {}

    def register(self, node_proc):
        self.nodes[node_proc.name] = node_proc

    def update_connectivity(self, matrix_str, ts):
        """
        Update connectivity matrix from flat string of length N*N (row-major).
        """
        if len(matrix_str) != self.N * self.N:
            print(f"ERROR: connectivity string length {len(matrix_str)} != {self.N}^2", file=sys.stderr)
            return
        with self._lock:
            for i, src in enumerate(self.node_names):
                for j, dst in enumerate(self.node_names):
                    self.conn[src][dst] = (matrix_str[i*self.N + j] == '1')
        # Log to simulator-wide stdout
        print(f"{ts:.3f},connectivity_update,{matrix_str}")

    def deliver_packet(self, src, hexdata):
        """
        Forward a transmit_packet from src to all reachable dst nodes.
        """
        with self._lock:
            for dst, allowed in self.conn.get(src, {}).items():
                if allowed and dst != src:
                    # send network_receive_packet
                    cmd = f"network_receive_packet,{hexdata}"
                    node = self.nodes.get(dst)
                    if node:
                        node.send_command(cmd)
                        # Log packet forwarding with sim timestamp
                        ts = node._timestamp()
                        print(f"{ts:.3f},forward,{src},{dst},{hexdata}", flush=True)
                        # Upon receipt, fetch and emit the node's state for live monitoring
                        try:
                            state_resp = node.get_state(timeout=0.2)
                            if state_resp:
                                print(f"{ts:.3f},state,{dst},{state_resp}", flush=True)
                        except Exception:
                            pass

def load_events(input_file):
    events = []
    with open(input_file) as f:
        for lineno, raw in enumerate(f, start=1):
            # Strip out full-line or inline comments (anything after '#')
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            parts = line.split(',', 2)
            if len(parts) < 3:
                print(f"Skipping malformed line {lineno}: {line}", file=sys.stderr)
                continue
            try:
                ts = float(parts[0])
            except ValueError:
                print(f"Invalid timestamp on line {lineno}: {parts[0]}", file=sys.stderr)
                continue
            dest = parts[1]
            data = parts[2]
            events.append((ts, dest, data))
    # assume input sorted; otherwise sort by ts
    events.sort(key=lambda x: x[0])
    return events

# Monitor live display code merged from monitor.py
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
        self.nodes = []
        self.events = {}
        self.connectivity = {}
        self.states = {}
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
        if ev == 'initialized':
            name = parts[2]
            self.add_node(name)
            return
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
            fields = parts[2].split(',', 1)
            if len(fields) < 1:
                return
            src = fields[0]
            self.events[src].append((ts, 'TX', 'TX'))
        elif ev == 'forward':
            fields = parts[2].split(',', 2)
            if len(fields) < 2:
                return
            src, dst = fields[0], fields[1]
            self.events[dst].append((ts, 'RX', src))
        elif ev == 'state':
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
        if self.mode == 'state':
            return self.generate_state_view()
        panels = []
        for n in sorted(self.nodes):
            text = Text()
            peers = sorted(self.connectivity.get(n, []))
            peers_str = ", ".join(peers) if peers else "<none>"
            text.append(f"Peers in: {peers_str}\n", style="cyan")
            text.append("Last events:\n", style="magenta")
            for ts, typ, other in list(self.events[n]):
                arrow = "→" if typ == 'TX' else "←"
                text.append(f" {ts:6.3f}s {arrow} {other}\n")
            panels.append(Panel(text, title=n, expand=True))
        return Columns(panels)

    def generate_state_view(self):
        panels = []
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LoRa network simulator orchestrator")
    parser.add_argument('--input', default=None,
                        help='Input command file; if omitted, enters interactive builder mode')
    parser.add_argument('--nodes', nargs='+', default=['ND01', 'ND02', 'ND03', 'ND04'],
                        help='List of node names')
    parser.add_argument('--node-exe', default='./network_simulator',
                        help='Path to network_simulator executable')
    parser.add_argument('--outdir', default='.', help='Directory for node log files')
    parser.add_argument('--duration', type=float, default=None,
                        help='Optional simulation duration in seconds')
    parser.add_argument('--monitor', choices=['events', 'state'], default=None,
                        help='Enable live monitor display using Rich')
    parser.add_argument('--spawn-offsets', nargs='+', type=float,
                        help='List of per-node spawn offsets (seconds). Overrides random offsets.')
    parser.add_argument('--spawn-max', type=float, default=5.0,
                        help='Maximum random spawn offset (seconds)')
    parser.add_argument('--seed', type=int, default=0,
                        help='Random seed for spawn offsets when not provided')
    args = parser.parse_args()

    # Interactive simulation: prompt for connectivity, spawn nodes, and accept live node_update via keys
    if args.input is None:
        # Prompt for connectivity matrix as raw bitstrings
        print("Interactive mode: enter connectivity for each node (bitstrings, no commas)", file=sys.__stdout__)
        matrix_rows = []
        for name in args.nodes:
            while True:
                resp = input(f"{name} reaches (bitstring length {len(args.nodes)}, e.g. "
                             f"{'0'*(len(args.nodes)-1)}1): ").strip()
                if len(resp) != len(args.nodes) or any(c not in ('0', '1') for c in resp):
                    print(f"Invalid: need {len(args.nodes)} digits 0/1", file=sys.__stdout__)
                else:
                    matrix_rows.append(resp)
                    break
        matrix_str = ''.join(matrix_rows)
        # Prepare simulation logs
        log_path = os.path.join(args.outdir, 'sim_output.log')
        sim_log = open(log_path, 'w', buffering=1)
        # Log connectivity_update at t=0
        line0 = f"{0.000:.3f},connectivity_update,{matrix_str}"
        print(line0, file=sys.__stdout__)
        sim_log.write(line0 + "\n")
        # Prepare simulation start and apply connectivity matrix
        start_time = time.time()
        dispatcher = Dispatcher(args.nodes)
        N = len(args.nodes)
        for i, src in enumerate(args.nodes):
            for j, dst in enumerate(args.nodes):
                dispatcher.conn[src][dst] = (matrix_str[i*N + j] == '1')
        # No nodes spawned yet; wait for keypress to spawn or update
        nodes = {}
        # Live key loop for node_update events
        print(f"Press keys 1-{len(args.nodes)} to generate node_update; ESC to finish.", file=sys.__stdout__)
        fd = sys.stdin.fileno()
        orig_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        try:
            while True:
                dr, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not dr:
                    continue
                ch = sys.stdin.read(1)
                if ch == '\x1b':  # ESC
                    break
                if ch.isdigit():
                    idx = int(ch) - 1
                    if 0 <= idx < len(args.nodes):
                        name = args.nodes[idx]
                        t = time.time() - start_time
                        tsf = f"{t:.3f}"
                        if name not in nodes:
                            # First press: spawn node
                            np = NodeProc(name, args.node_exe, args.outdir, start_time, dispatcher)
                            dispatcher.register(np)
                            nodes[name] = np
                            init_line = f"{tsf},initialized,{name}"
                            print(init_line, file=sys.__stdout__)
                            sim_log.write(init_line + "\n")
                        else:
                            # Subsequent press: node_update with random integer coords
                            t_int = int(t)
                            lat = random.randint(0, 100)
                            lon = random.randint(0, 100)
                            cmd = f"node_update,{name},{t_int},{lat},{lon}"
                            nodes[name].send_command(cmd)
                            evt = f"{tsf},send_command,{name},{cmd}"
                            print(f"Generated node_update for {name} at {t_int}s: {lat},{lon}", file=sys.__stdout__)
                            sim_log.write(evt + "\n")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, orig_settings)
        # Final state dump
        print("\nFinal node states:", file=sys.__stdout__)
        for name, np in nodes.items():
            resp = np.get_state(timeout=1.0)
            print(f"\n{name}:", file=sys.__stdout__)
            if not resp:
                print("  <no response>", file=sys.__stdout__)
            else:
                parts = resp.split(',')
                data = parts[2:]
                print(f"    {'Node':>4} {'TS':>5} {'Lat':>5} {'Lon':>5}", file=sys.__stdout__)
                for i in range(len(data)//4):
                    ename, ets, elat, elon = data[4*i:4*i+4]
                    print(f"    {ename:>4} {ets:>5} {elat:>5} {elon:>5}", file=sys.__stdout__)
        # Terminate nodes
        for np in nodes.values():
            np.terminate()
        print("Simulation terminated.", file=sys.__stdout__)
        sim_log.close()
        sys.exit(0)
    log_path = os.path.join(args.outdir, 'sim_output.log')
    sim_log = open(log_path, 'w', buffering=1)
    # Determine output streams: in monitor mode, send CSV only to log; otherwise, also to console
    if args.monitor:
        sys.stdout = Tee(sim_log)
    else:
        sys.stdout = Tee(sys.stdout, sim_log)

    # Prepare simulation
    start_time = time.time()
    dispatcher = Dispatcher(args.nodes)

    # Determine spawn offsets (absolute seconds since start)
    if args.spawn_offsets:
        if len(args.spawn_offsets) != len(args.nodes):
            print(f"Error: --spawn-offsets length {len(args.spawn_offsets)} != number of nodes {len(args.nodes)}", file=sys.stderr)
            sys.exit(1)
        offsets = args.spawn_offsets
    else:
        random.seed(args.seed)
        offsets = [random.uniform(0, args.spawn_max) for _ in args.nodes]

    # Spawn nodes at specified offsets (sorted by offset)
    schedule = sorted(zip(offsets, args.nodes), key=lambda x: x[0])
    nodes = {}
    for offset, name in schedule:
        now = time.time() - start_time
        to_sleep = offset - now
        if to_sleep > 0:
            time.sleep(to_sleep)
        np = NodeProc(name, args.node_exe, args.outdir, start_time, dispatcher)
        dispatcher.register(np)
        # Log node initialization event
        ts_init = np._timestamp()
        print(f"{ts_init:.3f},initialized,{name}", flush=True)
        nodes[name] = np

    # Load events
    events = load_events(args.input)

    # Loader thread
    def loader():
        for ts, dest, data in events:
            # wait until ts
            now = time.time() - start_time
            to_sleep = ts - now
            if to_sleep > 0:
                time.sleep(to_sleep)
            # dispatch
            if dest == '-1':
                dispatcher.update_connectivity(data, ts)
            else:
                np = nodes.get(dest)
                if np:
                    np.send_command(data)
                    # log overall
                    print(f"{ts:.3f},send_command,{dest},{data}")
                else:
                    print(f"Unknown destination '{dest}' at ts {ts}", file=sys.stderr)
    loader_thread = threading.Thread(target=loader, daemon=True)
    loader_thread.start()

    # Listen for Escape key to stop simulation and jump to get_state
    stop_event = threading.Event()
    # Start live monitor if requested
    if args.monitor:
        mon = Monitor()
        mon.mode = args.monitor
        def monitor_loop():
            with Live(mon.generate_view(), refresh_per_second=4, screen=True) as live:
                for line in tail_f(log_path):
                    if stop_event.is_set():
                        break
                    mon.parse_line(line)
                    live.update(mon.generate_view())
        threading.Thread(target=monitor_loop, daemon=True).start()
    if sys.stdin.isatty():
        fd = sys.stdin.fileno()
        orig_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        def esc_listener():
            while not stop_event.is_set():
                dr, _, _ = select.select([sys.stdin], [], [], 0.1)
                if dr:
                    ch = sys.stdin.read(1)
                    if ch == '\x1b':
                        stop_event.set()
                        break
        threading.Thread(target=esc_listener, daemon=True).start()
    try:
        if args.duration is not None:
            stop_event.wait(timeout=args.duration)
        else:
            # wait indefinitely until escape or interrupt
            stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        # Restore terminal settings if modified
        if sys.stdin.isatty():
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, orig_settings)

    # -- Final state dump --
    # Restore stdout to console for final summary if in monitor mode
    if args.monitor:
        sys.stdout = sys.__stdout__
    print("\nFinal node states:")
    for name in args.nodes:
        np = nodes[name]
        resp = np.get_state(timeout=1.0)
        print(f"\n{name}:")
        if not resp:
            print("  <no response>")
            continue
        parts = resp.split(',')
        # parts[0]=get_state, parts[1]=uptime_ms, then 4-tuples
        data = parts[2:]
        print(f"    {'Node':>4} {'Timestamp':>10} {'Lat':>10} {'Lon':>10}")
        for i in range(len(data)//4):
            ename, ets, elat, elon = data[4*i:4*i+4]
            print(f"    {ename:>4} {ets:>10} {elat:>10} {elon:>10}")

    # Terminate nodes
    for np in nodes.values():
        np.terminate()
    print("Simulation terminated.")