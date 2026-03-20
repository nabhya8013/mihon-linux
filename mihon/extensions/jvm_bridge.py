import subprocess
import json
import threading
import logging
import os
import time
from typing import Dict, Any, Optional, Callable
from concurrent.futures import Future

logger = logging.getLogger("jvm_bridge")


class JVMBridgeManager:
    """
    Manages the background Kotlin/Java daemon process that runs Tachiyomi
    extensions via JSON-RPC 2.0 over stdin/stdout.

    Usage:
        bridge = get_bridge()
        bridge.start()

        # Synchronous call
        result = bridge.call("system.ping")

        # Async call with callback
        bridge.send_request("extension.popular", {"extensionId": 123, "page": 1},
                            callback=lambda data: print(data))

        bridge.stop()
    """
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = JVMBridgeManager()
        return cls._instance

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self.ready = False
        self._lock = threading.Lock()
        self._request_id = 0
        self._pending: Dict[int, Future] = {}
        self._callbacks: Dict[int, Callable] = {}
        self._ready_event = threading.Event()

        # Path to the compiled bridge jar
        self.jar_path = os.path.join(
            os.path.dirname(__file__),
            "../../bridge/build/libs/mihon-bridge-1.0-SNAPSHOT.jar"
        )

    def start(self):
        """Start the JVM bridge process."""
        with self._lock:
            if self.running:
                return True

            if not os.path.exists(self.jar_path):
                logger.warning(
                    f"Bridge JAR not found at {self.jar_path}. "
                    f"Build with: cd bridge && ./gradlew jar"
                )
                return False

            logger.info("Starting JVM Bridge...")
            try:
                # Use JDK 21 since the bridge is compiled with Kotlin 1.9
                java_home = os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-21-openjdk")
                java_bin = os.path.join(java_home, "bin", "java")
                if not os.path.exists(java_bin):
                    java_bin = "java"  # fallback to system java

                env = os.environ.copy()
                env["JAVA_HOME"] = java_home

                self.process = subprocess.Popen(
                    [java_bin, "-jar", self.jar_path],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,  # line-buffered
                    env=env,
                )
                self.running = True
                self._ready_event.clear()

                # Start listener threads
                threading.Thread(target=self._read_stdout, daemon=True, name="jvm-stdout").start()
                threading.Thread(target=self._read_stderr, daemon=True, name="jvm-stderr").start()

                # Wait for ready signal (up to 15 seconds)
                if self._ready_event.wait(timeout=15):
                    logger.info("JVM Bridge is ready.")
                    return True
                else:
                    logger.warning("JVM Bridge started but no ready signal received within 15s.")
                    return True  # Still usable, just slow startup

            except FileNotFoundError:
                logger.error("Java not found. Please install a JDK (e.g., openjdk-17-jdk).")
                return False
            except Exception as e:
                logger.error(f"Failed to start JVM Bridge: {e}")
                return False

    def _read_stdout(self):
        """Read JSON-RPC responses from the bridge's stdout."""
        while self.running and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
            except Exception:
                break

            if not line:
                break
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.debug(f"[JVM STDOUT non-JSON]: {line}")
                continue

            # Check for bridge.ready notification
            if data.get("method") == "bridge.ready":
                self.ready = True
                self._ready_event.set()
                logger.info(f"Bridge ready: {data.get('params', {})}")
                continue

            # Route to pending request
            req_id = data.get("id")
            if req_id is not None:
                # Resolve pending future
                future = self._pending.pop(req_id, None)
                if future is not None:
                    if "error" in data and data["error"]:
                        future.set_exception(
                            BridgeError(data["error"].get("message", "Unknown error"),
                                        data["error"].get("code", -1))
                        )
                    else:
                        future.set_result(data.get("result"))

                # Fire callback if registered
                cb = self._callbacks.pop(req_id, None)
                if cb:
                    try:
                        cb(data)
                    except Exception as e:
                        logger.error(f"Callback error for request {req_id}: {e}")
            else:
                logger.debug(f"[JVM response no id]: {data}")

        # Process died
        if self.running:
            logger.warning("JVM Bridge stdout closed unexpectedly.")
            self.running = False
            self.ready = False
            # Fail all pending futures
            for future in self._pending.values():
                future.set_exception(BridgeError("Bridge process died", -1))
            self._pending.clear()

    def _read_stderr(self):
        """Read diagnostic logging from the bridge's stderr."""
        while self.running and self.process and self.process.stderr:
            try:
                line = self.process.stderr.readline()
            except Exception:
                break
            if not line:
                break
            logger.info(f"[JVM] {line.strip()}")

    def call(self, method: str, params: dict = None, timeout: float = 30.0) -> Any:
        """
        Synchronous JSON-RPC call. Blocks until response is received.

        Args:
            method:  RPC method name (e.g., "system.ping", "extension.popular")
            params:  Method parameters dict
            timeout: Max seconds to wait for response

        Returns:
            The 'result' field from the JSON-RPC response.

        Raises:
            BridgeError: On RPC error or timeout
        """
        if not self.running or not self.process or not self.process.stdin:
            raise BridgeError("Bridge is not running", -1)

        future = Future()
        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            self._pending[req_id] = future

        request = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": req_id
        })

        try:
            self.process.stdin.write(request + "\n")
            self.process.stdin.flush()
        except BrokenPipeError:
            self._pending.pop(req_id, None)
            self.stop()
            raise BridgeError("Bridge pipe broken", -1)

        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            self._pending.pop(req_id, None)
            raise BridgeError(f"Timeout waiting for response to {method}", -1)

    def send_request(self, method: str, params: dict = None, callback: Callable = None):
        """
        Asynchronous JSON-RPC call. Returns immediately; callback is invoked on response.
        """
        if not self.running or not self.process or not self.process.stdin:
            logger.error("Bridge is not running!")
            return

        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            if callback:
                self._callbacks[req_id] = callback

        request = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": req_id
        })

        try:
            self.process.stdin.write(request + "\n")
            self.process.stdin.flush()
        except BrokenPipeError:
            self.stop()

    def stop(self):
        """Stop the JVM bridge process."""
        with self._lock:
            self.running = False
            self.ready = False
            if self.process:
                try:
                    self.process.stdin.write("exit\n")
                    self.process.stdin.flush()
                    self.process.wait(timeout=5)
                except Exception:
                    try:
                        self.process.terminate()
                    except Exception:
                        pass
                self.process = None
            # Fail all pending
            for future in self._pending.values():
                future.set_exception(BridgeError("Bridge stopped", -1))
            self._pending.clear()
            self._callbacks.clear()

    def is_running(self) -> bool:
        return self.running and self.ready


class BridgeError(Exception):
    """Error from the JVM bridge."""
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def get_bridge() -> JVMBridgeManager:
    """Get the singleton bridge manager instance."""
    return JVMBridgeManager.get_instance()
