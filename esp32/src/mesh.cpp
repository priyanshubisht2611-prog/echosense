/**
 * EchoSense Mesh Networking Protocol for ESP32 WROOM
 * AODV-like routing protocol for peer-to-peer device communication
 */

#include "mesh.h"
#include <cstring>

// Constants
#define DISCOVERY_INTERVAL 10000      // 10 seconds
#define CLEANUP_INTERVAL 60000       // 60 seconds
#define NEIGHBOR_TIMEOUT 60000       // 60 seconds
#define ROUTE_TIMEOUT 300000         // 5 minutes
#define MAX_PAYLOAD_SIZE 64
#define UDP_BUFFER_SIZE 128

// MeshMessage serialization
std::vector<uint8_t> MeshMessage::toBytes() const {
    std::vector<uint8_t> data;
    
    // Header: type(1) + source(4) + destination(4) + seq(4) + hop(1) + max_hop(1) + payload_len(1) = 16 bytes
    data.push_back(static_cast<uint8_t>(msgType));
    data.insert(data.end(), source, source + 4);
    data.insert(data.end(), destination, destination + 4);
    
    // Add sequence number (little endian)
    data.push_back(sequenceNumber & 0xFF);
    data.push_back((sequenceNumber >> 8) & 0xFF);
    data.push_back((sequenceNumber >> 16) & 0xFF);
    data.push_back((sequenceNumber >> 24) & 0xFF);
    
    data.push_back(hopCount);
    data.push_back(maxHops);
    data.push_back(payloadLength);
    
    // Add payload
    data.insert(data.end(), payload, payload + payloadLength);
    
    return data;
}

// MeshMessage deserialization
MeshMessage MeshMessage::fromBytes(const uint8_t* data, size_t length) {
    MeshMessage msg;
    
    if (length < 16) return msg;  // Invalid message
    
    size_t offset = 0;
    
    msg.msgType = static_cast<MessageType>(data[offset++]);
    memcpy(msg.source, data + offset, 4);
    offset += 4;
    memcpy(msg.destination, data + offset, 4);
    offset += 4;
    
    msg.sequenceNumber = data[offset] | (data[offset+1] << 8) | (data[offset+2] << 16) | (data[offset+3] << 24);
    offset += 4;
    
    msg.hopCount = data[offset++];
    msg.maxHops = data[offset++];
    msg.payloadLength = data[offset++];
    
    if (length >= offset + msg.payloadLength && msg.payloadLength <= MAX_PAYLOAD_SIZE) {
        memcpy(msg.payload, data + offset, msg.payloadLength);
    }
    
    return msg;
}

// MeshNetwork constructor
MeshNetwork::MeshNetwork(const String& deviceId, uint16_t listenPort)
    : _deviceId(deviceId), _listenPort(listenPort), _running(false),
      _sequenceNumber(0), _lastDiscovery(0), _lastCleanup(0) {
}

// MeshNetwork destructor
MeshNetwork::~MeshNetwork() {
    stop();
}

// Start the mesh network
bool MeshNetwork::begin() {
    if (_running) return true;
    
    if (_udp.begin(_listenPort)) {
        _running = true;
        _lastDiscovery = millis();
        _lastCleanup = millis();
        Serial.printf("[MESH] Started on port %d\n", _listenPort);
        return true;
    }
    
    Serial.println("[MESH] Failed to start UDP");
    return false;
}

// Stop the mesh network
void MeshNetwork::stop() {
    _running = false;
    _udp.stop();
    Serial.println("[MESH] Stopped");
}

// Add a neighbor manually
void MeshNetwork::addNeighbor(const String& deviceId, const String& ip, uint16_t port, float signalStrength) {
    Neighbor neighbor;
    neighbor.deviceId = deviceId;
    neighbor.ip = ip;
    neighbor.port = port;
    neighbor.lastSeen = millis();
    neighbor.signalStrength = signalStrength;
    neighbor.hopCount = 1;
    
    _neighbors[deviceId] = neighbor;
    Serial.printf("[MESH] Added neighbor: %s at %s:%d\n", deviceId.c_str(), ip.c_str(), port);
}

// Send data to destination
bool MeshNetwork::sendData(const String& destination, const uint8_t* data, size_t length) {
    if (length > MAX_PAYLOAD_SIZE) {
        Serial.println("[MESH] Payload too large");
        return false;
    }
    
    // Check if destination is a direct neighbor
    if (_neighbors.count(destination)) {
        MeshMessage msg;
        msg.msgType = DATA;
        strncpy(msg.source, _deviceId.c_str(), 4);
        strncpy(msg.destination, destination.c_str(), 4);
        msg.sequenceNumber = _getSequenceNumber();
        msg.hopCount = 0;
        msg.payloadLength = length;
        memcpy(msg.payload, data, length);
        
        _sendTo(msg.toBytes().data(), msg.toBytes().size(), destination);
        return true;
    }
    
    // Check if we have a route
    if (_routes.count(destination)) {
        RouteEntry& route = _routes[destination];
        MeshMessage msg;
        msg.msgType = DATA;
        strncpy(msg.source, _deviceId.c_str(), 4);
        strncpy(msg.destination, destination.c_str(), 4);
        msg.sequenceNumber = _getSequenceNumber();
        msg.hopCount = 0;
        msg.payloadLength = length;
        memcpy(msg.payload, data, length);
        
        _sendTo(msg.toBytes().data(), msg.toBytes().size(), route.nextHop);
        route.lastUsed = millis();
        return true;
    }
    
    // No route, initiate route discovery
    Serial.printf("[MESH] No route to %s, initiating discovery\n", destination.c_str());
    MeshMessage rreq;
    rreq.msgType = ROUTE_REQUEST;
    strncpy(rreq.source, _deviceId.c_str(), 4);
    strncpy(rreq.destination, destination.c_str(), 4);
    rreq.sequenceNumber = _getSequenceNumber();
    rreq.hopCount = 0;
    rreq.maxHops = 10;
    rreq.payloadLength = 0;
    
    _broadcast(rreq.toBytes().data(), rreq.toBytes().size());
    _pendingRoutes[destination] = millis();
    return false;
}

// Set callback for received data
void MeshNetwork::onDataReceived(DataCallback callback) {
    _dataCallback = callback;
}

// Get current topology
void MeshNetwork::getTopology(std::vector<Neighbor>& neighbors, std::vector<RouteEntry>& routes) {
    neighbors.clear();
    routes.clear();
    
    for (const auto& pair : _neighbors) {
        neighbors.push_back(pair.second);
    }
    
    for (const auto& pair : _routes) {
        routes.push_back(pair.second);
    }
}

// Update loop (call this in main loop)
void MeshNetwork::update() {
    if (!_running) return;
    
    unsigned long now = millis();
    
    // Handle incoming UDP packets
    int packetSize = _udp.parsePacket();
    if (packetSize > 0) {
        uint8_t buffer[UDP_BUFFER_SIZE];
        int len = _udp.read(buffer, sizeof(buffer));
        if (len > 0) {
            String remoteIp = _udp.remoteIP().toString();
            uint16_t remotePort = _udp.remotePort();
            _handleMessage(buffer, len, remoteIp, remotePort);
        }
    }
    
    // Send discovery beacons periodically
    if (now - _lastDiscovery > DISCOVERY_INTERVAL) {
        _sendDiscovery();
        _lastDiscovery = now;
    }
    
    // Cleanup stale neighbors and expired routes
    if (now - _lastCleanup > CLEANUP_INTERVAL) {
        _cleanupStaleNeighbors();
        _cleanupExpiredRoutes();
        _lastCleanup = now;
    }
}

// Get statistics
uint16_t MeshNetwork::getNeighborCount() const {
    return _neighbors.size();
}

uint16_t MeshNetwork::getRouteCount() const {
    return _routes.size();
}

// Send discovery beacon
void MeshNetwork::_sendDiscovery() {
    MeshMessage msg;
    msg.msgType = DISCOVERY;
    strncpy(msg.source, _deviceId.c_str(), 4);
    strncpy(msg.destination, "BCST", 4);
    msg.sequenceNumber = _getSequenceNumber();
    msg.hopCount = 0;
    msg.payloadLength = 0;
    
    std::vector<uint8_t> data = msg.toBytes();
    _broadcast(data.data(), data.size());
    Serial.println("[MESH] Sent discovery beacon");
}

// Broadcast to all neighbors
void MeshNetwork::_broadcast(const uint8_t* data, size_t length) {
    for (const auto& pair : _neighbors) {
        const Neighbor& neighbor = pair.second;
        _udp.beginPacket(neighbor.ip.c_str(), neighbor.port);
        _udp.write(data, length);
        _udp.endPacket();
    }
}

// Send to specific device
void MeshNetwork::_sendTo(const uint8_t* data, size_t length, const String& deviceId) {
    if (_neighbors.count(deviceId)) {
        const Neighbor& neighbor = _neighbors[deviceId];
        _udp.beginPacket(neighbor.ip.c_str(), neighbor.port);
        _udp.write(data, length);
        _udp.endPacket();
    } else {
        Serial.printf("[MESH] Unknown device: %s\n", deviceId.c_str());
    }
}

// Handle incoming message
void MeshNetwork::_handleMessage(const uint8_t* data, size_t length, const String& remoteIp, uint16_t remotePort) {
    MeshMessage msg = MeshMessage::fromBytes(data, length);
    String source = _extractDeviceId(msg.source);
    
    // Update neighbor if this is from a direct neighbor
    if (source != _deviceId && msg.hopCount == 0) {
        addNeighbor(source, remoteIp, remotePort);
    }
    
    // Handle based on message type
    switch (msg.msgType) {
        case DISCOVERY:
            _handleDiscovery(msg, remoteIp, remotePort);
            break;
        case ROUTE_REQUEST:
            _handleRouteRequest(msg);
            break;
        case ROUTE_REPLY:
            _handleRouteReply(msg);
            break;
        case DATA:
            _handleData(msg);
            break;
        case ACK:
            // Handle acknowledgment
            Serial.printf("[MESH] Received ACK from %s\n", source.c_str());
            break;
        default:
            Serial.println("[MESH] Unknown message type");
            break;
    }
}

// Handle discovery message
void MeshNetwork::_handleDiscovery(const MeshMessage& msg, const String& remoteIp, uint16_t remotePort) {
    String source = _extractDeviceId(msg.source);
    if (source != _deviceId) {
        addNeighbor(source, remoteIp, remotePort);
    }
}

// Handle route request
void MeshNetwork::_handleRouteRequest(const MeshMessage& msg) {
    String destination = _extractDeviceId(msg.destination);
    
    if (destination == _deviceId) {
        // We are the destination, send route reply
        MeshMessage reply;
        reply.msgType = ROUTE_REPLY;
        strncpy(reply.source, _deviceId.c_str(), 4);
        strncpy(reply.destination, _extractDeviceId(msg.source).c_str(), 4);
        reply.sequenceNumber = _getSequenceNumber();
        reply.hopCount = 0;
        reply.payloadLength = msg.source[0];  // Store original destination in first byte
        memcpy(reply.payload, msg.source, 4);
        
        std::vector<uint8_t> data = reply.toBytes();
        _sendTo(data.data(), data.size(), _extractDeviceId(msg.source));
    } else if (msg.hopCount < msg.maxHops) {
        // Forward the route request
        MeshMessage forwardMsg = msg;
        forwardMsg.hopCount++;
        std::vector<uint8_t> data = forwardMsg.toBytes();
        _broadcast(data.data(), data.size());
    }
}

// Handle route reply
void MeshNetwork::_handleRouteReply(const MeshMessage& msg) {
    String destination = _extractDeviceId(msg.destination);
    
    if (destination == _deviceId) {
        // Route reply is for us
        String originalDest = _extractDeviceId(reinterpret_cast<const char*>(msg.payload));
        
        RouteEntry route;
        route.destination = originalDest;
        route.nextHop = _extractDeviceId(msg.source);
        route.hopCount = msg.hopCount + 1;
        route.sequenceNumber = msg.sequenceNumber;
        route.lastUsed = millis();
        route.expires = millis() + ROUTE_TIMEOUT;
        
        _routes[originalDest] = route;
        Serial.printf("[MESH] Route established to %s via %s (hops: %d)\n", 
                      originalDest.c_str(), route.nextHop.c_str(), route.hopCount);
    } else if (msg.hopCount < msg.maxHops) {
        // Forward the route reply
        MeshMessage forwardMsg = msg;
        forwardMsg.hopCount++;
        std::vector<uint8_t> data = forwardMsg.toBytes();
        _sendTo(data.data(), data.size(), destination);
    }
}

// Handle data message
void MeshNetwork::_handleData(const MeshMessage& msg) {
    String destination = _extractDeviceId(msg.destination);
    
    if (destination == _deviceId) {
        // Data is for us, deliver to application
        String source = _extractDeviceId(msg.source);
        Serial.printf("[MESH] Received data from %s (hops: %d)\n", source.c_str(), msg.hopCount);
        
        if (_dataCallback) {
            _dataCallback(source, msg.payload, msg.payloadLength, msg.hopCount);
        }
    } else if (msg.hopCount < msg.maxHops) {
        // Forward data
        _forwardData(msg);
    }
}

// Forward data message
void MeshNetwork::_forwardData(const MeshMessage& msg) {
    String destination = _extractDeviceId(msg.destination);
    
    // Check if we have a route to destination
    if (_routes.count(destination)) {
        RouteEntry& route = _routes[destination];
        MeshMessage forwardMsg = msg;
        forwardMsg.hopCount++;
        
        std::vector<uint8_t> data = forwardMsg.toBytes();
        _sendTo(data.data(), data.size(), route.nextHop);
        route.lastUsed = millis();
    } else {
        // No route, broadcast to neighbors (flood)
        MeshMessage forwardMsg = msg;
        forwardMsg.hopCount++;
        std::vector<uint8_t> data = forwardMsg.toBytes();
        _broadcast(data.data(), data.size());
    }
}

// Cleanup stale neighbors
void MeshNetwork::_cleanupStaleNeighbors() {
    unsigned long now = millis();
    std::vector<String> stale;
    
    for (const auto& pair : _neighbors) {
        if (now - pair.second.lastSeen > NEIGHBOR_TIMEOUT) {
            stale.push_back(pair.first);
        }
    }
    
    for (const String& deviceId : stale) {
        _neighbors.erase(deviceId);
        Serial.printf("[MESH] Removed stale neighbor: %s\n", deviceId.c_str());
    }
}

// Cleanup expired routes
void MeshNetwork::_cleanupExpiredRoutes() {
    unsigned long now = millis();
    std::vector<String> expired;
    
    for (const auto& pair : _routes) {
        if (now > pair.second.expires) {
            expired.push_back(pair.first);
        }
    }
    
    for (const String& destination : expired) {
        _routes.erase(destination);
        Serial.printf("[MESH] Removed expired route to: %s\n", destination.c_str());
    }
}

// Get next sequence number
uint32_t MeshNetwork::_getSequenceNumber() {
    return ++_sequenceNumber;
}

// Extract device ID from 4-byte array
String MeshNetwork::_extractDeviceId(const char* deviceId) {
    char id[5];
    memcpy(id, deviceId, 4);
    id[4] = '\0';
    return String(id);
}
