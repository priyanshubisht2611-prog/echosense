# EchoSense Mesh Networking for ESP32 WROOM

AODV-like routing protocol for peer-to-peer device communication on ESP32 WROOM microcontrollers.

## Features

- **Neighbor Discovery**: Automatic discovery of nearby mesh nodes
- **Route Discovery**: AODV-like routing protocol for multi-hop communication
- **Packet Forwarding**: Automatic forwarding of data packets through mesh network
- **Hop Count Tracking**: Track number of hops for each message
- **Topology Management**: Maintain network topology and route tables
- **Backend Integration**: Send topology data to backend server for visualization

## Hardware Requirements

- ESP32 WROOM (or any ESP32 variant)
- WiFi connection
- Minimum 520KB SRAM (standard ESP32)

## Software Requirements

- PlatformIO IDE or Arduino IDE
- ESP32 Arduino Core
- No external libraries required (uses built-in Arduino libraries)

## Installation

### Using PlatformIO (Recommended)

1. Install PlatformIO IDE extension in VS Code
2. Clone the repository
3. Open the `esp32` folder in PlatformIO
4. Build and upload:
   ```
   pio run --target upload
   ```

### Using Arduino IDE

1. Install ESP32 board support in Arduino IDE
2. Copy `mesh.h` and `mesh.cpp` to your project
3. Copy `main.cpp` to your project (rename to `.ino` if needed)
4. Install required libraries (none required for mesh)
5. Build and upload

## Configuration

Edit `main.cpp` to configure:

```cpp
// WiFi credentials
const char* WIFI_SSID = "your_wifi_ssid";
const char* WIFI_PASSWORD = "your_wifi_password";

// Mesh network configuration
const String DEVICE_ID = "NODE01";  // 4-character device ID
const uint16_t MESH_PORT = 9000;

// Backend server configuration
const char* BACKEND_HOST = "192.168.1.100";
const uint16_t BACKEND_PORT = 8000;
```

## API Reference

### MeshNetwork Class

#### Constructor
```cpp
MeshNetwork(const String& deviceId, uint16_t listenPort = 9000);
```

#### Methods

- `bool begin()` - Start the mesh network
- `void stop()` - Stop the mesh network
- `void addNeighbor(const String& deviceId, const String& ip, uint16_t port, float signalStrength = 0.0)` - Add neighbor manually
- `bool sendData(const String& destination, const uint8_t* data, size_t length)` - Send data to destination
- `void onDataReceived(DataCallback callback)` - Set callback for received data
- `void getTopology(std::vector<Neighbor>& neighbors, std::vector<RouteEntry>& routes)` - Get current topology
- `void update()` - Update loop (call in main loop)
- `uint16_t getNeighborCount()` - Get number of neighbors
- `uint16_t getRouteCount()` - Get number of routes

### Data Callback

```cpp
void onDataReceived(const String& source, const uint8_t* data, size_t length, uint8_t hopCount);
```

Called when data is received from another mesh node.

## Protocol Details

### Message Types

- `DISCOVERY (0x01)` - Neighbor discovery beacon
- `ROUTE_REQUEST (0x02)` - Route discovery request
- `ROUTE_REPLY (0x03)` - Route discovery reply
- `DATA (0x04)` - Data message
- `ACK (0x05)` - Acknowledgment

### Message Format

```
[Type:1][Source:4][Dest:4][Seq:4][Hop:1][MaxHop:1][PayloadLen:1][Payload:0-64]
```

### Routing Protocol

1. **Discovery**: Nodes periodically broadcast discovery beacons
2. **Route Discovery**: When sending to unknown destination, broadcast RREQ
3. **Route Reply**: Destination responds with RREP containing route info
4. **Data Forwarding**: Data packets forwarded along established routes
5. **Route Maintenance**: Routes expire after 5 minutes of inactivity

## Memory Optimization

The implementation is optimized for ESP32's limited memory:

- Fixed-size buffers (no dynamic allocation)
- Maximum payload size: 64 bytes
- Neighbor and route tables use efficient STL containers
- Periodic cleanup of stale entries

## Limitations

- Device ID limited to 4 characters
- Maximum payload: 64 bytes
- Maximum hop count: 10
- No encryption (add TLS/DTLS if needed)
- No authentication (implement if needed)

## Integration with EchoSense Backend

The mesh network can send topology data to the EchoSense backend:

```cpp
void sendTopologyToBackend() {
    // Get topology
    std::vector<Neighbor> neighbors;
    std::vector<RouteEntry> routes;
    mesh.getTopology(neighbors, routes);
    
    // Send to backend via HTTP POST
    // Endpoint: POST /api/mesh/topology
}
```

## Example Usage

```cpp
#include "mesh.h"

MeshNetwork mesh("NODE01", 9000);

void setup() {
    Serial.begin(115200);
    WiFi.begin("SSID", "PASSWORD");
    
    while (WiFi.status() != WL_CONNECTED) {
        delay(100);
    }
    
    mesh.begin();
    mesh.onDataReceived(onDataReceived);
}

void loop() {
    mesh.update();
    
    // Send data
    uint8_t data[] = {0x01, 0x02, 0x03};
    mesh.sendData("NODE02", data, sizeof(data));
    
    delay(10);
}

void onDataReceived(const String& source, const uint8_t* data, size_t length, uint8_t hopCount) {
    Serial.printf("Received from %s, hops: %d\n", source.c_str(), hopCount);
}
```

## Troubleshooting

### WiFi Connection Issues
- Check SSID and password
- Ensure ESP32 has good WiFi signal
- Check router settings (2.4GHz only)

### Mesh Not Discovering Neighbors
- Ensure all devices are on same WiFi network
- Check firewall settings
- Verify MESH_PORT is not blocked
- Check device IDs are unique

### Route Discovery Fails
- Ensure destination device is online
- Check hop count limits
- Verify network connectivity

## License

Same as parent EchoSense project.

## Contributing

Contributions welcome! Please submit pull requests to the main repository.
