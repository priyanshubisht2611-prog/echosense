/**
 * EchoSense Mesh Networking Example for ESP32 WROOM
 * Demonstrates mesh networking protocol with peer-to-peer communication
 */

#include <Arduino.h>
#include <WiFi.h>
#include "mesh.h"

// WiFi credentials
const char* WIFI_SSID = "your_wifi_ssid";
const char* WIFI_PASSWORD = "your_wifi_password";

// Mesh network configuration
const String DEVICE_ID = "NODE01";  // 4-character device ID
const uint16_t MESH_PORT = 9000;

// Backend server configuration
const char* BACKEND_HOST = "192.168.1.100";
const uint16_t BACKEND_PORT = 8000;

// Mesh network instance
MeshNetwork mesh(DEVICE_ID, MESH_PORT);

// WiFi client for backend communication
WiFiClient backendClient;

// Timing variables
unsigned long lastBackendUpdate = 0;
const unsigned long BACKEND_UPDATE_INTERVAL = 30000;  // 30 seconds

// Data received callback
void onDataReceived(const String& source, const uint8_t* data, size_t length, uint8_t hopCount) {
    Serial.printf("[APP] Received data from %s (hops: %d, length: %d)\n", 
                  source.c_str(), hopCount, length);
    
    // Process received data (e.g., forward to backend)
    // In this example, we just print the data
    Serial.print("[APP] Data: ");
    for (size_t i = 0; i < length && i < 32; i++) {
        Serial.printf("%02X ", data[i]);
    }
    Serial.println();
}

// Send topology to backend
void sendTopologyToBackend() {
    if (!backendClient.connected()) {
        if (!backendClient.connect(BACKEND_HOST, BACKEND_PORT)) {
            Serial.println("[APP] Failed to connect to backend");
            return;
        }
    }
    
    // Get topology
    std::vector<Neighbor> neighbors;
    std::vector<RouteEntry> routes;
    mesh.getTopology(neighbors, routes);
    
    // Build JSON payload
    String payload = "{";
    payload += "\"device_id\":\"" + DEVICE_ID + "\",";
    payload += "\"neighbors\":[";
    
    for (size_t i = 0; i < neighbors.size(); i++) {
        if (i > 0) payload += ",";
        payload += "{";
        payload += "\"device_id\":\"" + neighbors[i].deviceId + "\",";
        payload += "\"ip\":\"" + neighbors[i].ip + "\",";
        payload += "\"port\":" + String(neighbors[i].port) + ",";
        payload += "\"signal_strength\":" + String(neighbors[i].signalStrength) + ",";
        payload += "\"hop_count\":" + String(neighbors[i].hopCount);
        payload += "}";
    }
    
    payload += "],";
    payload += "\"routes\":[";
    
    for (size_t i = 0; i < routes.size(); i++) {
        if (i > 0) payload += ",";
        payload += "{";
        payload += "\"destination\":\"" + routes[i].destination + "\",";
        payload += "\"next_hop\":\"" + routes[i].nextHop + "\",";
        payload += "\"hop_count\":" + String(routes[i].hopCount);
        payload += "}";
    }
    
    payload += "]}";
    
    // Send to backend
    backendClient.println("POST /api/mesh/topology HTTP/1.1");
    backendClient.println("Host: " + String(BACKEND_HOST));
    backendClient.println("Content-Type: application/json");
    backendClient.println("Content-Length: " + String(payload.length()));
    backendClient.println("Connection: keep-alive");
    backendClient.println();
    backendClient.println(payload);
    
    Serial.println("[APP] Sent topology to backend");
}

// Send detection to backend via mesh
void sendDetectionViaMesh(const String& destination, const uint8_t* data, size_t length) {
    if (mesh.sendData(destination, data, length)) {
        Serial.println("[APP] Sent detection via mesh");
    } else {
        Serial.println("[APP] Route discovery in progress");
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println("\n===========================================");
    Serial.println("🦉 EchoSense Mesh Networking - ESP32");
    Serial.println("===========================================");
    
    // Connect to WiFi
    Serial.printf("[WiFi] Connecting to %s...\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    
    Serial.println();
    Serial.printf("[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    
    // Initialize mesh network
    if (mesh.begin()) {
        Serial.println("[MESH] Mesh network initialized");
    } else {
        Serial.println("[MESH] Failed to initialize mesh network");
        while (1) delay(1000);
    }
    
    // Set data callback
    mesh.onDataReceived(onDataReceived);
    
    // Add manual neighbors (optional - for testing)
    // mesh.addNeighbor("NODE02", "192.168.1.101", 9000, -65.0);
    
    Serial.println("[APP] Setup complete");
}

void loop() {
    // Update mesh network (handle incoming messages, discovery, cleanup)
    mesh.update();
    
    // Periodically send topology to backend
    unsigned long now = millis();
    if (now - lastBackendUpdate > BACKEND_UPDATE_INTERVAL) {
        sendTopologyToBackend();
        lastBackendUpdate = now;
    }
    
    // Example: Send a test detection every 60 seconds
    static unsigned long lastTest = 0;
    if (now - lastTest > 60000) {
        uint8_t testData[] = {0x01, 0x02, 0x03, 0x04};  // Example detection data
        sendDetectionViaMesh("NODE02", testData, sizeof(testData));
        lastTest = now;
    }
    
    // Print statistics every 30 seconds
    static unsigned long lastStats = 0;
    if (now - lastStats > 30000) {
        Serial.printf("[STATS] Neighbors: %d, Routes: %d\n", 
                      mesh.getNeighborCount(), mesh.getRouteCount());
        lastStats = now;
    }
    
    delay(10);  // Small delay to prevent watchdog issues
}
