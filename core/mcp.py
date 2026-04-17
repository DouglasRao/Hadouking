import asyncio
import json
import os
from typing import Dict, Any, List, Optional

class MCPClient:
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.command = config.get("command")
        self.args = config.get("args", [])
        self.env = config.get("env", {})
        self.cwd = config.get("cwd", os.getcwd())
        self.process: Optional[asyncio.subprocess.Process] = None
        self.request_id = 0
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.tools: List[Dict[str, Any]] = []

    async def connect(self):
        """Starts the MCP server subprocess and initializes connection."""
        try:
            # Merge environment variables
            env = os.environ.copy()
            env.update(self.env)

            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.cwd
            )
            
            # HACK: Increase the StreamReader limit to handle large JSON payloads (e.g. from hexstrike-ai)
            # Default is 64KB, increasing to 10MB
            if self.process.stdout:
                try:
                    # Depending on python version/implementation, this might vary.
                    # For standard asyncio StreamReader:
                    self.process.stdout._limit = 10 * 1024 * 1024 
                except Exception:
                    pass
            
            # Start reading stdout in background
            asyncio.create_task(self._read_loop())
            
            # Initialize handshake
            await self._initialize()
            
            # Fetch tools
            await self.refresh_tools()
            
            return True
        except Exception as e:
            print(f"Failed to connect to MCP server {self.name}: {e}")
            return False

    async def _read_loop(self):
        """Reads JSON-RPC messages from stdout."""
        if not self.process or not self.process.stdout:
            return

        try:
            while True:
                try:
                    # Use a large buffer for readline
                    line = await self.process.stdout.readline()
                    if not line:
                        break

                    line_str = line.decode().strip()
                    if not line_str:
                        continue

                    # Parse JSON-RPC
                    try:
                        message = json.loads(line_str)
                        await self._handle_message(message)
                    except json.JSONDecodeError:
                        pass
                except asyncio.LimitOverrunError:
                    print(f"[{self.name}] Error: Line too long (exceeded limit). Skipping line.")
                    try:
                        await self.process.stdout.read(1024*1024)
                    except Exception:
                        pass
                except Exception as e:
                    print(f"Error reading from {self.name}: {e}")
                    break
        finally:
            # Process died or EOF — fail all pending requests
            for req_id, future in list(self.pending_requests.items()):
                if not future.done():
                    future.set_exception(Exception(f"MCP server '{self.name}' disconnected"))
            self.pending_requests.clear()

    async def _handle_message(self, message: Dict[str, Any]):
        """Handles incoming JSON-RPC messages."""
        if "id" in message and message["id"] in self.pending_requests:
            # Response to a request
            future = self.pending_requests.pop(message["id"])
            if "error" in message:
                future.set_exception(Exception(message["error"].get("message", "Unknown error")))
            else:
                future.set_result(message.get("result"))
        elif "method" in message:
            # Notification or request from server (not fully handled yet)
            pass

    async def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> Any:
        """Sends a JSON-RPC request and waits for response."""
        if not self.process or not self.process.stdin:
            raise Exception("Not connected")

        self.request_id += 1
        req_id = self.request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        future = asyncio.Future()
        self.pending_requests[req_id] = future

        try:
            self.process.stdin.write(json.dumps(request).encode() + b"\n")
            await self.process.stdin.drain()
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.pending_requests.pop(req_id, None)
            raise Exception(f"MCP request '{method}' timed out after {timeout}s")
        except Exception as e:
            self.pending_requests.pop(req_id, None)
            raise e

    async def _initialize(self):
        """Performs MCP initialization handshake."""
        response = await self._send_request("initialize", {
            "protocolVersion": "0.1.0",
            "capabilities": {},
            "clientInfo": {"name": "Hadouking", "version": "2.0"}
        })
        
        # Send initialized notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        self.process.stdin.write(json.dumps(notification).encode() + b"\n")
        await self.process.stdin.drain()

    async def refresh_tools(self):
        """Fetches available tools from the server."""
        response = await self._send_request("tools/list")
        self.tools = response.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Executes a tool on the MCP server."""
        response = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        return response

    async def disconnect(self):
        """Terminates the connection."""
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass
            self.process = None
