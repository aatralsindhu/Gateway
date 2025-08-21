import time
import json
import paho.mqtt.client as mqtt
from Gateway.models import IHG_MQTTConfiguration ,IHG_OutboundConnector,IHG_InboundConnector,IHG_MQTTData
from Gateway.rest_connector import send_data_to_api
from datetime import datetime
# MQTT message callback
def on_message(client, userdata, msg):
    payload_str  = msg.payload.decode()
    print("Raw payload:", payload_str , type(payload_str ))
    connector_type = userdata.get("type")
    connector_id = userdata.get("connector_id")
   
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        payload = {}
        print(f"❌ Failed to decode JSON payload: {payload_str}")

    if connector_type == "inbound":
        inbound_connector = IHG_InboundConnector.objects.get(id=connector_id)
        gateway = inbound_connector.gateway  # assumes inbound connector has FK gateway
        outbound_connectors = IHG_OutboundConnector.objects.filter(gateway=gateway)
        print(f"➡ Forwarding data to {len(outbound_connectors)} outbound connectors")
        device_name = payload.get("node")
        ts = payload.get("timestamp")
        inbound_connector.status = "active"
        inbound_connector.save(update_fields=["status"])
        timestamp = datetime.fromtimestamp(ts / 1000)  # convert ms → seconds
        values = payload.get("values", {})
        mqtt_config = userdata.get("mqtt_config")  # pass this when connecting

        for key, val in values.items():
            IHG_MQTTData.objects.create(
                config=mqtt_config,
                device_name=device_name,
                key=key,
                value=val,
                timestamp=timestamp,
            )
        for outbound in outbound_connectors:
            if outbound.connector_type == "mqtt":
                # Find MQTT config
                try:
                    config = IHG_MQTTConfiguration.objects.get(connector_outbound=outbound)
                    mqtt_pub_client = mqtt.Client()
                    mqtt_pub_client.username_pw_set(config.username or "", config.password or "")
                    mqtt_pub_client.connect(config.broker_ip, config.port, keepalive=60)
                    mqtt_pub_client.publish(config.topic, json.dumps(payload))
                    mqtt_pub_client.disconnect()
                    print(f"➡ Forwarded to MQTT Outbound {outbound.name} on {config.topic}")
                except Exception as e:
                    print(f"⚠ Failed to forward to outbound MQTT: {e}")

            elif outbound.connector_type == "rest":
                try:
                    url = outbound.rest_url  # assumes outbound has endpoint_url field
                    send_data_to_api(url,payload,outbound.id)
                    print(f"➡ Forwarded to REST Outbound {outbound.name}")
                except Exception as e:
                    print(f"⚠ Failed to forward to outbound REST: {e}")

def on_connect(client, userdata, flags, rc):
    connector_id = userdata.get("connector_id")
    type = userdata.get("type")
    connector = None
    try:
        print("connector_type",type)
        if type == "inbound":
           
            connector = IHG_InboundConnector.objects.get(id=connector_id)
        else:
            
            connector = IHG_OutboundConnector.objects.get(id=connector_id)
    except Exception as e:
        print(f"⚠ Connector {connector_id} not found: {e}")
        return
    if rc == 0:
        print("✅ MQTT Connected successfully")
        connector.status = "active"
        connector.save(update_fields=["status"])
        # Subscribe to assigned topics after connection
        print("userdata",userdata.get("topics", []))
        for topic in userdata.get("topics", []):
            if topic and isinstance(topic, str) and topic.strip():
                try:
                    client.subscribe(topic.strip())
                    print(f"📡 Subscribed to topic: {topic.strip()}")
                except Exception as e:
                    print(f"⚠ Failed to subscribe to topic '{topic}': {e}")
            else:
                print(f"⚠ Skipping invalid/empty topic: {topic}")

    else:
        print(f"❌ MQTT Connection failed. Code: {rc}")
        connector.status = "inactive"
        connector.save(update_fields=["status"])


def mqtt_loop():
    """Loop over all MQTT configurations and keep them connected."""
    configs = IHG_MQTTConfiguration.objects.all()

    clients = []

    for config in configs:
        try:
            connector = None
            type = None
            if config.connector_inbound_id:
                connector = config.connector_inbound
                type = 'inbound'
                
            elif config.connector_outbound_id:
                connector = config.connector_outbound
                type = 'outbound'

            if not connector:
                print(f"⚠ MQTT config {config.id} has no linked connector")
                continue
            topics = [config.topic]

            client = mqtt.Client(client_id=f"gateway_{connector.id}", userdata={"topics": topics,"connector_id": connector.id,"type":type,"mqtt_config" : connector.mqtt_config})
            print("userdata",{"topics": topics,"connector_id": connector.id})
            client.username_pw_set(config.username or "", config.password or "")
            client.on_connect = on_connect
            client.on_message = on_message

            print(f"🔌 Connecting to MQTT broker {config.broker_ip}:{config.port}")
            client.connect(config.broker_ip, config.port, keepalive=60)

            clients.append(client)
        except Exception as e:
            print(f"⚠ Failed to set up MQTT for {config}: {e}")

    # Start loops
    for client in clients:
        client.loop_start()

    # Keep running
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("🛑 Stopping MQTT clients...")
        for client in clients:
            client.loop_stop()
            client.disconnect()
