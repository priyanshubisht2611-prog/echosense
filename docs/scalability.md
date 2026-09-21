# 📈 Scalability Architecture

EchoSense is engineered to scale from a single forest station to thousands of interconnected nodes.

## 1. Zero-Config Node Auto-Registration
The platform treats field hardware as "disposable and discoverable." 
- Nodes only need their pre-assigned `device_id` and GPS coordinates.
- On the first transmission, the backend builds the node's profile, history, and status tracking automatically.

## 2. Low-Bandwidth Efficiency
By strictly enforcing the **22-byte protocol**, EchoSense minimizes radio airtime. 
- **Higher Node Density**: Less airtime means more devices can share the same frequency without collision.
- **Cost Reduction**: Minimal data payloads reduce satellite and cellular backhaul charges significantly.

## 3. Edge Resiliency (Store-and-Forward)
Every node operates with an independent **Local SQLite Buffer**.
- **Offline Mode**: If the gateway is down, the node continues to store detections locally.
- **Batch Flush**: Upon reconnection, the node chronologically replays its buffer to the server, ensuring no temporal gaps in ecological data.

## 4. Concurrent Backend Processing
- **Horizontal Scaling**: The FastAPI backend is stateless; it can be replicated behind a load balancer (Nginx/Kubernetes) to handle millions of packets.
- **DB Integrity**: Leverages SQL-level constraints to handle racing ingestion packets without data corruption.
