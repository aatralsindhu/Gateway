import time
import json
import paho.mqtt.client as mqtt
from Gateway.models import IHG_MQTTConfiguration ,IHG_OutboundConnector,IHG_InboundConnector,IHG_MQTTData,IHG_MQTTDevice
from Gateway.rest_connector import send_data_to_api
from datetime import datetime
import threading
import paho.mqtt.publish as publish

mqtt_thread = None
mqtt_thread_stop_event = threading.Event()
clients_lock = threading.Lock()
mqtt_clients = []
inbound_data_cache = {}
cache_lock = threading.Lock()
def mqtt_topic_match(subscription, topic):
    sub_parts = subscription.strip('/').split('/')
    topic_parts = topic.strip('/').split('/')

    if len(sub_parts) != len(topic_parts):
        return False

    for sub_part, topic_part in zip(sub_parts, topic_parts):
        if sub_part == '+':
            continue
        if sub_part != topic_part:
            return False
    return True

# Load allowed devices and timeseries per inbound connector and topic for filtering
def load_allowed_timeseries(inbound_connector,msg_topic):
    print("msg_topic",msg_topic)
    allowed = {}
    for topic in inbound_connector.mqtt_config.topics.all():
        if mqtt_topic_match(topic.name, msg_topic):
            for device in topic.devices.all():
                allowed_device_key_set = set(ts.key for ts in device.timeseries.all())
                allowed[device.device_name] = allowed_device_key_set
            break
    return allowed

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
        if ts is not None:
            timestamp = datetime.fromtimestamp(ts / 1000)  # convert ms → seconds
        else:
            timestamp = datetime.now()  # fallback to current time if timestamp is missing

        values = payload.get("values", {})
        mqtt_config = userdata.get("mqtt_config")  # pass this when connecting
        allowed_keys_map = load_allowed_timeseries(inbound_connector,msg.topic)
        print("allowed_keys_map",allowed_keys_map)
        if device_name not in allowed_keys_map:
            print(f"⚠ Device '{device_name}' not recognized for inbound connector '{inbound_connector.name}',allowed_keys_map'{allowed_keys_map}'")
        else:
            device_objs = IHG_MQTTDevice.objects.filter(device_name=device_name)
            if not device_objs.exists():
                print(f"⚠ Device '{device_name}' not found")
                device_obj = None
            else:
                device_obj = device_objs.first()

            allowed_keys = allowed_keys_map[device_name]

            with cache_lock:
                print("inbound_data_cache",inbound_data_cache)

                if connector_id not in inbound_data_cache:
                    inbound_data_cache[connector_id] = {}
                
                device_cache = inbound_data_cache[connector_id].get(device_name)
                if device_cache is None:
                    inbound_data_cache[connector_id][device_name] = {}
                    device_cache = inbound_data_cache[connector_id][device_name]
                    print(f'Created new cache for device {device_name}')
                else:
                    print(f'Using existing cache for device {device_name}')

                # Filter and update only defined keys
                for k, v in values.items():
                    if k in allowed_keys:
                        device_cache[k] = v
                        IHG_MQTTData.objects.create(
                        device=device_obj,
                        key=k,
                        value=v,
                        timestamp=timestamp,
                    )
                print("device_cache",device_cache)
        
        
def forward_outbound_data(outbound_connector):
    print(f"🔄 Preparing data for outbound connector: {outbound_connector.name}")
    inbound_connector = IHG_InboundConnector.objects.get(gateway=outbound_connector.gateway)  # Simplify for demo
    connector_id = inbound_connector.id

    with cache_lock:
        data_to_send = inbound_data_cache.get(connector_id, {})
        # Prepare structured payload
        payload = {
            'timestamp': int(time.time() * 1000),
            'data': data_to_send
        }
        # Clear cache after read
        inbound_data_cache[connector_id] = {}

    # Send based on outbound type
    if outbound_connector.connector_type == 'rest':
        print("payload",payload)
        if mqtt_clients !=[]:
            send_data_to_api(outbound_connector.rest_url, payload, outbound_connector.id)

    elif outbound_connector.connector_type == 'mqtt':
        config = outbound_connector.mqtt_config
      
        topics = config.topics.all()
        
    
        auth = {
    "username": config.username if config.username is not None else "",
    "password": config.password if config.password is not None else ""
}

        # for topic in topics:
            
        #     publish.single(
        #     topic=topic.name,
        #     payload=json.dumps(payload),
        #     hostname=config.broker_ip,
        #     port=config.port
        # )
        client = mqtt.Client()
        if config.username:
            client.username_pw_set(config.username, config.password or "")

        client.connect(config.broker_ip, config.port, keepalive=60)

        for topic in topics:          
            print("topic",topic.name)
            client.publish(
                topic=topic.name,
                payload=json.dumps(payload),
                qos=0, retain=False
            )      


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
    global mqtt_clients
    mqtt_clients = []
    """Loop over all MQTT configurations and keep them connected."""
    configs = IHG_MQTTConfiguration.objects.all()

    
    with clients_lock:
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
                topics = list(config.topics.values_list('name', flat=True))
                print(f"Topics for connector {connector.name}: {topics}")
                client = mqtt.Client(client_id=f"gateway_{connector.id}", userdata={"topics": topics,"connector_id": connector.id,"type":type,"mqtt_config" : connector.mqtt_config})
                print("userdata",{"topics": topics,"connector_id": connector.id})
                mqtt_clients.append(client)
                client.username_pw_set(config.username or "", config.password or "")
                client.on_connect = on_connect
                print("client_______",client)
                client.on_message = on_message
                

                print(f"🔌 Connecting to MQTT broker {config.broker_ip}:{config.port}")
                client.connect(config.broker_ip, config.port, keepalive=60)

                client.loop_start()
            except Exception as e:
                print(f"⚠ Failed to set up MQTT for {config}: {e}")

    
    try:
        while not mqtt_thread_stop_event.is_set():
            time.sleep(1)
    finally:
        # On stop event, stop all clients cleanly
        with clients_lock:
            for client in mqtt_clients:
                try:
                    client.loop_stop()  # Stop network loop
                    client.disconnect() # Disconnect from broker
                except Exception as e:
                    print(f"⚠ Error stopping mqtt client: {e}")
            mqtt_clients.clear()



def start_mqtt_loop():
    global mqtt_thread, mqtt_thread_stop_event
    if mqtt_thread and mqtt_thread.is_alive():
        print("Stopping current MQTT thread before restart")
        stop_mqtt_loop()
    mqtt_thread_stop_event.clear()
    mqtt_thread = threading.Thread(target=mqtt_loop, daemon=True)
    mqtt_thread.start()

def stop_mqtt_loop():
    global mqtt_thread, mqtt_thread_stop_event
    if mqtt_thread and mqtt_thread.is_alive():
        mqtt_thread_stop_event.set()
        mqtt_thread.join(timeout=5)
        print("MQTT loop stopped")
    mqtt_thread = None


def run_outbound_connector_loop(connector):
    gateway_id = connector.gateway.id
    in_connector = IHG_InboundConnector.objects.get(gateway=gateway_id)
    print("in_connector",in_connector.interval)
    interval = int(in_connector.interval)
    while True:
        forward_outbound_data(connector)
        time.sleep(interval)

def start_outbound_loops():
    connectors = list(IHG_OutboundConnector.objects.all())
    if connectors:
        for connector in connectors:
            thread = threading.Thread(target=run_outbound_connector_loop, args=(connector,), daemon=True)
            thread.start()

# Call this once to start all loops
start_outbound_loops()


