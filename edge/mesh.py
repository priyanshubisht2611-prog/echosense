"""
Mesh networking module for EchoSense edge devices.

Implements a simple AODV-like routing protocol for peer-to-peer communication
between edge devices in a wireless mesh network.
"""

import time
import random
import struct
import threading
import socket
import json
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger("mesh")


class MessageType(Enum):
    """Message types for mesh protocol."""
    DISCOVERY = 0x01
    ROUTE_REQUEST = 0x02
    ROUTE_REPLY = 0x03
    DATA = 0x04
    ACK = 0x05


@dataclass
class Neighbor:
    """Represents a neighboring device in the mesh network."""
    device_id: str
    ip: str
    port: int
    last_seen: float = field(default_factory=time.time)
    signal_strength: float = 0.0  # RSSI in dBm
    hop_count: int = 1


@dataclass
class RouteEntry:
    """Represents a route to a destination device."""
    destination: str
    next_hop: str
    hop_count: int
    sequence_number: int = 0
    last_used: float = field(default_factory=time.time)
    expires: float = field(default_factory=lambda: time.time() + 300)  # 5 min TTL


@dataclass
class MeshMessage:
    """A message in the mesh network."""
    msg_type: MessageType
    source: str
    destination: str
    sequence_number: int
    hop_count: int = 0
    max_hops: int = 10
    payload: bytes = b""
    previous_hop: Optional[str] = None

    def to_bytes(self) -> bytes:
        """Serialize message to bytes."""
        header = struct.pack(
            "!B4s4sIHHH",
            self.msg_type.value,
            self.source.encode("utf-8")[:4].ljust(4, b"\x00"),
            self.destination.encode("utf-8")[:4].ljust(4, b"\x00"),
            self.sequence_number,
            self.hop_count,
            self.max_hops,
            len(self.payload)
        )
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "MeshMessage":
        """Deserialize message from bytes."""
        if len(data) < 17:
            raise ValueError("Message too short")
        
        msg_type, src_bytes, dst_bytes, seq_num, hop_count, max_hops, payload_len = struct.unpack(
            "!B4s4sIHHH", data[:17]
        )
        
        source = src_bytes.decode("utf-8", errors="ignore").strip("\x00")
        destination = dst_bytes.decode("utf-8", errors="ignore").strip("\x00")
        payload = data[17:17+payload_len]
        
        return cls(
            msg_type=MessageType(msg_type),
            source=source,
            destination=destination,
            sequence_number=seq_num,
            hop_count=hop_count,
            max_hops=max_hops,
            payload=payload
        )


class MeshNetwork:
    """
    Mesh networking manager for edge devices.
    
    Implements neighbor discovery, route discovery, and packet forwarding.
    """
    
    def __init__(self, device_id: str, listen_port: int = 9000):
        self.device_id = device_id
        self.listen_port = listen_port
        self.neighbors: Dict[str, Neighbor] = {}
        self.routes: Dict[str, RouteEntry] = {}
        self.sequence_number = 0
        self.pending_routes: Dict[str, float] = {}  # destination -> request time
        self.message_queue: List[Tuple[str, bytes]] = []  # (destination, payload)
        
        self.running = False
        self.listen_thread: Optional[threading.Thread] = None
        self.discovery_thread: Optional[threading.Thread] = None
        
        # Socket for mesh communication
        self.socket: Optional[socket.socket] = None
        
    def start(self):
        """Start the mesh network manager."""
        if self.running:
            return
        
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("0.0.0.0", self.listen_port))
        self.socket.settimeout(1.0)
        
        # Start listener thread
        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()
        
        # Start discovery thread
        self.discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self.discovery_thread.start()
        
        logger.info(f"[MESH] Started on port {self.listen_port}")
        
    def stop(self):
        """Stop the mesh network manager."""
        self.running = False
        if self.socket:
            self.socket.close()
        logger.info("[MESH] Stopped")
        
    def add_neighbor(self, device_id: str, ip: str, port: int, signal_strength: float = 0.0):
        """Add or update a neighbor."""
        neighbor = Neighbor(
            device_id=device_id,
            ip=ip,
            port=port,
            last_seen=time.time(),
            signal_strength=signal_strength
        )
        self.neighbors[device_id] = neighbor
        logger.debug(f"[MESH] Added/updated neighbor: {device_id} at {ip}:{port}")
        
    def _listen_loop(self):
        """Listen for incoming mesh messages."""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(1024)
                self._handle_message(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"[MESH] Listen error: {e}")
                
    def _discovery_loop(self):
        """Periodically send discovery beacons."""
        while self.running:
            self._send_discovery()
            self._cleanup_stale_neighbors()
            self._cleanup_expired_routes()
            time.sleep(10)  # Discovery interval
            
    def _send_discovery(self):
        """Send a discovery beacon to broadcast address."""
        msg = MeshMessage(
            msg_type=MessageType.DISCOVERY,
            source=self.device_id,
            destination="BROADCAST",
            sequence_number=self._get_sequence_number(),
            payload=b""
        )
        self._broadcast(msg.to_bytes())
        logger.debug("[MESH] Sent discovery beacon")
        
    def _broadcast(self, data: bytes):
        """Broadcast message to all known neighbors."""
        for neighbor in self.neighbors.values():
            try:
                self.socket.sendto(data, (neighbor.ip, neighbor.port))
            except Exception as e:
                logger.warning(f"[MESH] Failed to send to {neighbor.device_id}: {e}")
                
    def _handle_message(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming mesh message."""
        try:
            msg = MeshMessage.from_bytes(data)
        except Exception as e:
            logger.error(f"[MESH] Failed to parse message: {e}")
            return
        
        # Update neighbor if this is from a direct neighbor
        if msg.source != self.device_id and msg.hop_count == 0:
            self.add_neighbor(msg.source, addr[0], addr[1])
        
        # Handle based on message type
        if msg.msg_type == MessageType.DISCOVERY:
            self._handle_discovery(msg, addr)
        elif msg.msg_type == MessageType.ROUTE_REQUEST:
            self._handle_route_request(msg, addr)
        elif msg.msg_type == MessageType.ROUTE_REPLY:
            self._handle_route_reply(msg, addr)
        elif msg.msg_type == MessageType.DATA:
            self._handle_data(msg, addr)
        elif msg.msg_type == MessageType.ACK:
            self._handle_ack(msg, addr)
            
    def _handle_discovery(self, msg: MeshMessage, addr: Tuple[str, int]):
        """Handle discovery beacon from neighbor."""
        if msg.source != self.device_id:
            self.add_neighbor(msg.source, addr[0], addr[1])
            
    def _handle_route_request(self, msg: MeshMessage, addr: Tuple[str, int]):
        """Handle route request (AODV-like)."""
        if msg.destination == self.device_id:
            # We are the destination, send route reply
            reply = MeshMessage(
                msg_type=MessageType.ROUTE_REPLY,
                source=self.device_id,
                destination=msg.source,
                sequence_number=self._get_sequence_number(),
                hop_count=0,
                payload=msg.source.encode("utf-8")
            )
            self._send_to(reply.to_bytes(), msg.source)
        elif msg.hop_count < msg.max_hops:
            # Forward the route request
            msg.hop_count += 1
            msg.previous_hop = self.device_id
            self._broadcast(msg.to_bytes())
            
    def _handle_route_reply(self, msg: MeshMessage, addr: Tuple[str, int]):
        """Handle route reply."""
        if msg.destination == self.device_id:
            # Route reply is for us, extract route
            original_dest = msg.payload.decode("utf-8", errors="ignore")
            route = RouteEntry(
                destination=original_dest,
                next_hop=msg.source,
                hop_count=msg.hop_count + 1,
                sequence_number=msg.sequence_number
            )
            self.routes[original_dest] = route
            logger.info(f"[MESH] Route established to {original_dest} via {msg.source} (hops: {route.hop_count})")
        elif msg.hop_count < msg.max_hops:
            # Forward the route reply
            msg.hop_count += 1
            self._send_to(msg.to_bytes(), msg.destination)
            
    def _handle_data(self, msg: MeshMessage, addr: Tuple[str, int]):
        """Handle data message."""
        if msg.destination == self.device_id:
            # Data is for us, deliver to application
            logger.info(f"[MESH] Received data from {msg.source} (hops: {msg.hop_count})")
            # In real implementation, this would be passed to application callback
        elif msg.hop_count < msg.max_hops:
            # Forward data
            msg.hop_count += 1
            msg.previous_hop = self.device_id
            self._forward_data(msg)
            
    def _handle_ack(self, msg: MeshMessage, addr: Tuple[str, int]):
        """Handle acknowledgment."""
        logger.debug(f"[MESH] Received ACK from {msg.source}")
        
    def _forward_data(self, msg: MeshMessage):
        """Forward data message along route."""
        # Check if we have a route to destination
        if msg.destination in self.routes:
            route = self.routes[msg.destination]
            self._send_to(msg.to_bytes(), route.next_hop)
            route.last_used = time.time()
        else:
            # No route, broadcast to neighbors (flood)
            self._broadcast(msg.to_bytes())
            
    def _send_to(self, data: bytes, device_id: str):
        """Send message to specific device."""
        if device_id in self.neighbors:
            neighbor = self.neighbors[device_id]
            try:
                self.socket.sendto(data, (neighbor.ip, neighbor.port))
            except Exception as e:
                logger.warning(f"[MESH] Failed to send to {device_id}: {e}")
        else:
            logger.warning(f"[MESH] Unknown device: {device_id}")
            
    def _get_sequence_number(self) -> int:
        """Get next sequence number."""
        self.sequence_number += 1
        return self.sequence_number
        
    def _cleanup_stale_neighbors(self):
        """Remove neighbors not seen in 60 seconds."""
        now = time.time()
        stale = [k for k, v in self.neighbors.items() if now - v.last_seen > 60]
        for k in stale:
            del self.neighbors[k]
            logger.debug(f"[MESH] Removed stale neighbor: {k}")
            
    def _cleanup_expired_routes(self):
        """Remove expired routes."""
        now = time.time()
        expired = [k for k, v in self.routes.items() if now > v.expires]
        for k in expired:
            del self.routes[k]
            logger.debug(f"[MESH] Removed expired route to: {k}")
            
    def send_data(self, destination: str, payload: bytes) -> bool:
        """
        Send data to destination through mesh network.
        
        Returns True if data was sent (queued), False if route not found.
        """
        if destination in self.neighbors:
            # Direct neighbor, send immediately
            msg = MeshMessage(
                msg_type=MessageType.DATA,
                source=self.device_id,
                destination=destination,
                sequence_number=self._get_sequence_number(),
                hop_count=0,
                payload=payload
            )
            self._send_to(msg.to_bytes(), destination)
            return True
        elif destination in self.routes:
            # Have a route, send via next hop
            route = self.routes[destination]
            msg = MeshMessage(
                msg_type=MessageType.DATA,
                source=self.device_id,
                destination=destination,
                sequence_number=self._get_sequence_number(),
                hop_count=0,
                payload=payload
            )
            self._send_to(msg.to_bytes(), route.next_hop)
            return True
        else:
            # No route, initiate route discovery
            logger.info(f"[MESH] No route to {destination}, initiating discovery")
            rreq = MeshMessage(
                msg_type=MessageType.ROUTE_REQUEST,
                source=self.device_id,
                destination=destination,
                sequence_number=self._get_sequence_number(),
                hop_count=0,
                max_hops=10
            )
            self._broadcast(rreq.to_bytes())
            self.pending_routes[destination] = time.time()
            return False
            
    def get_topology(self) -> Dict:
        """Get current network topology for visualization."""
        return {
            "device_id": self.device_id,
            "neighbors": [
                {
                    "device_id": n.device_id,
                    "ip": n.ip,
                    "port": n.port,
                    "signal_strength": n.signal_strength,
                    "last_seen": n.last_seen
                }
                for n in self.neighbors.values()
            ],
            "routes": [
                {
                    "destination": r.destination,
                    "next_hop": r.next_hop,
                    "hop_count": r.hop_count,
                    "last_used": r.last_used
                }
                for r in self.routes.values()
            ]
        }
