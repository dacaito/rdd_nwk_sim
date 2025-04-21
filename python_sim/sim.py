#!/usr/bin/env python3
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LoRa network simulator orchestrator")
    parser.add_argument('--input', default='input.log', help='Input command file')
    parser.add_argument('--nodes', nargs='+', default=['NOD1', 'NOD2', 'NOD3', 'NOD4'],
                        help='List of node names')
    parser.add_argument('--node-exe', default='./network_simulator',
                        help='Path to network_simulator executable')
    parser.add_argument('--outdir', default='.', help='Directory for node log files')
    parser.add_argument('--duration', type=float, default=None,
                        help='Optional simulation duration in seconds')
    args = parser.parse_args()

    # Setup sim_output.log to capture all orchestrator stdout
    log_path = os.path.join(args.outdir, 'sim_output.log')
    sim_log = open(log_path, 'w', buffering=1)
    sys.stdout = Tee(sys.stdout, sim_log)

    # Prepare
    start_time = time.time()
    dispatcher = Dispatcher(args.nodes)
    # Spawn nodes
    nodes = {}
    for name in args.nodes:
        time.sleep(random.uniform(0,5))
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