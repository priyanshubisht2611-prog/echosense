/**
 * EchoSense Mesh Networking Protocol for ESP32 WROOM
 * AODV-like routing protocol for peer-to-peer device communication
 */

#ifndef MESH_H
#define MESH_H

#include <WiFi.h>
#include <WiFiUDP.h>
#include <Arduino.h>
#include <vector>
#include <map>
#include <string>
#include <functional>

// Message types for mesh protocol
enum MessageType : uint8_t {
    DISCOVERY = 0x01,
    ROUTE_REQUEST = 0x02,
    ROUTE_REPLY = 0x03,
    DATA = 0x04,
    ACK = 0x05
};

// Neighbor structure
struct Neighbor {
    String deviceId;
    String ip;
    uint16_t port;
    unsigned long lastSeen;
    float signalStrength;
    uint8_t hopCount;
    
    Neighbor() : port(0), lastSeen(0), signalStrength(0.0), hopCount(1) {}
};

// Route entry structure
struct RouteEntry {
    String destination;
    String nextHop;
    uint8_t hopCount;
    uint16_t sequenceNumber;
    unsigned long lastUsed;
    unsigned long expires;
    
    RouteEntry() : hopCount(0), sequenceNumber(0), lastUsed(0), expires(0) {}
};

// Mesh message structure
struct MeshMessage {
    MessageType msgType;
    char source[5];      // 4 char device ID + null terminator
    char destination[5]; // 4 char device ID + null terminator
    uint32_t sequenceNumber;
    uint8_t hopCount;
    uint8_t maxHops;
    uint8_t payloadLength;
    uint8_t payload[64]; // Max 64 bytes payload
    
    MeshMessage() : msgType(DISCOVERY), sequenceNumber(0), hopCount(0), 
                    maxHops(10), payloadLength(0) {
        memset(source, 0, sizeof(source));
        memset(destination, 0, sizeof(destination));
        memset(payload, 0, sizeof(payload));
    }
    
    // Serialize to bytes
    std::vector<uint8_t> toBytes() const;
    
    // Deserialize from bytes
    static MeshMessage fromBytes(const uint8_t* data, size_t length);
};

// Mesh network manager class
class MeshNetwork {
public:
    // Callback type for received data messages
    using DataCallback = std::function<void(const String& source, const uint8_t* data, size_t length, uint8_t hopCount)>;
    
    MeshNetwork(const String& deviceId, uint16_t listenPort = 9000);
    ~MeshNetwork();
    
    // Start/stop the mesh network
    bool begin();
    void stop();
    
    // Add a neighbor manually
    void addNeighbor(const String& deviceId, const String& ip, uint16_t port, float signalStrength = 0.0);
    
    // Send data to destination
    bool sendData(const String& destination, const uint8_t* data, size_t length);
    
    // Set callback for received data
    void onDataReceived(DataCallback callback);
    
    // Get current topology
    void getTopology(std::vector<Neighbor>& neighbors, std::vector<RouteEntry>& routes);
    
    // Update loop (call this in main loop)
    void update();
    
    // Get statistics
    uint16_t getNeighborCount() const;
    uint16_t getRouteCount() const;
    
private:
    String _deviceId;
    uint16_t _listenPort;
    WiFiUDP _udp;
    bool _running;
    
    std::map<String, Neighbor> _neighbors;
    std::map<String, RouteEntry> _routes;
    std::map<String, unsigned long> _pendingRoutes;
    
    uint32_t _sequenceNumber;
    unsigned long _lastDiscovery;
    unsigned long _lastCleanup;
    
    DataCallback _dataCallback;
    
    // Internal methods
    void _sendDiscovery();
    void _handleMessage(const uint8_t* data, size_t length, const String& remoteIp, uint16_t remotePort);
    void _handleDiscovery(const MeshMessage& msg, const String& remoteIp, uint16_t remotePort);
    void _handleRouteRequest(const MeshMessage& msg);
    void _handleRouteReply(const MeshMessage& msg);
    void _handleData(const MeshMessage& msg);
    void _handleAck(const MeshMessage& msg);
    void _forwardData(const MeshMessage& msg);
    void _sendTo(const uint8_t* data, size_t length, const String& deviceId);
    void _broadcast(const uint8_t* data, size_t length);
    void _cleanupStaleNeighbors();
    void _cleanupExpiredRoutes();
    uint32_t _getSequenceNumber();
    String _extractDeviceId(const char* deviceId);
};

#endif // MESH_H
