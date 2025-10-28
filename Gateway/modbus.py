import time
from django.db import connection
from datetime import datetime, timedelta
from pymodbus.client import ModbusTcpClient
from Gateway.models import (
    IHG_InboundConnector,
    IHG_OutboundConnector,
    IHG_MQTTConfiguration,
    Device,
    IHG_Timeseries,
    IHG_ModbusData,
    IHG_Gateway, Rule
)
import json
import paho.mqtt.client as mqtt
from Gateway.models import (
    IHG_InboundConnector,
    IHG_OutboundConnector,
    IHG_MQTTConfiguration,
    Device,
    IHG_Timeseries,
    IHG_ModbusData
)
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
import json
import time
from datetime import datetime
import requests
from django.utils.timezone import now
import threading
import asyncio
modbus_thread = None
modbus_thread_stop_event = threading.Event()
from Gateway.openadr_ven import openadr_clients
from Gateway.ocpp_connector import ocpp_clients 
from Gateway.mappings import measurand_mapping




def publish_to_mqtt(gateway, device_name, connector_id, values):
    try:
        # 1️⃣ Find outbound MQTT connector for the same gateway
        outbound_connector = IHG_OutboundConnector.objects.filter(
            gateway=gateway, connector_type='mqtt'
        ).first()

        if not outbound_connector:
            print(f"⚠ No outbound MQTT connector found for gateway {gateway.name}")
            return

        # 2️⃣ Get MQTT configuration
        mqtt_config = getattr(outbound_connector, "mqtt_config", None)
        if not mqtt_config:
            print(f"⚠ No MQTT configuration found for outbound connector {outbound_connector.name}")
            return

        # 3️⃣ Prepare MQTT client
        client = mqtt.Client()
        if mqtt_config.username:
            client.username_pw_set(mqtt_config.username, mqtt_config.password or "")

        client.connect(mqtt_config.broker_ip, mqtt_config.port, keepalive=60)

        # 4️⃣ Prepare payload
        payload = {
            "node": device_name,
            "group": str(connector_id),
            "timestamp": int(time.time() * 1000),
            "values": values,
            "errors": {}
        }

        topics = mqtt_config.topics.all()
        for  topic in topics:
            print("topic",topic.name)
        #     publish.single(
        #     topic=topic.name,
        #     payload=json.dumps(payload),
        #     hostname=mqtt_config.broker_ip,
        #     port=mqtt_config.port
        # )
            client.publish(topic.name, json.dumps(payload))
        client.disconnect()
        print(f"📤 MQTT Published for {device_name} to topic {topic}")
        
    except Exception as e:
        print(f"❌ MQTT publish failed for {device_name}: {e}")
        

def read_modbus_timeseries(connector):
    """Read Modbus timeseries for a single connector."""
    print(f"🔌 Checking connector: {connector.name}")

    devices = Device.objects.filter(connector=connector)
    connector_active = False

    for device in devices:
        ip = device.device_ip
        port = device.device_port

        errors = {}
        print(f"   📡 Connecting to device {device.device_name} ({ip}:{port})")
        client = ModbusTcpClient(ip, port=port)

        if client.connect():
            print(f"   ✅ Device {device.device_name} connected")
            device.device_status = "active"
            device.save(update_fields=["device_status"])
            connector_active = True  # At least one device is active
            values_dict = {}
            ts_list = IHG_Timeseries.objects.filter(device=device)
            for ts in ts_list:
                try:
                    result = client.read_holding_registers(address=int(ts.address), count=1)
                    if result.isError():
                        print(f"      ⚠ Error reading {ts.name}")
                        continue
                    value = result.registers[0] * ts.scale
                    # IHG_ModbusData.objects.create(timeseries=ts, value=value)
                    values_dict[ts.name] = value
                    print(f"      📊 TS {ts.name} = {value}")
                except Exception as e:
                    print(f"      ❌ Error reading TS {ts.id}: {e}")
            max_points = int(connector.maximum_data_points) if connector.maximum_data_points else None

                   
            insert_timeseries_value(connector.name, device.device_name,values_dict,max_points)

            client.close()
            if values_dict:
                outbound_connectors = IHG_OutboundConnector.objects.filter(gateway=connector.gateway)

                for ob_connector in outbound_connectors:
                    if ob_connector.connector_type == "mqtt":
                        print(f"   📤 Publishing to MQTT via {ob_connector.name}")
                        rules = Rule.objects.filter(stream=connector)
                        if not rules.exists() or rules.actions == "inactive":
                            publish_to_mqtt(
                                gateway=connector.gateway,
                                device_name=device.device_name,
                                connector_id=connector.connector_id,
                                values=values_dict
                            )
                        else:
                            for rule in rules:
                                sql = rule.sql
                                with connection.cursor() as cursor:
                                    try:
                                        cursor.execute(sql)
                                        # fetch results if needed
                                        rows = cursor.fetchall()
                                        column_names = [desc[0] for desc in cursor.description]

                                        # build list of dicts with column_name: value mapping
                                        results_with_columns = [dict(zip(column_names, row)) for row in rows]
                                    except Exception as e:
                                        print(f"   ❌ SQL execution error: {e}")
                                        results_with_columns = e
                                    publish_to_mqtt(
                                        gateway=connector.gateway,
                                        device_name=device.device_name,
                                        connector_id=connector.connector_id,
                                        values=results_with_columns
                                    )


                    elif ob_connector.connector_type == "rest":
                        try:
                            rules = Rule.objects.filter(stream=connector)
                            if not rules.exists() or rules.actions == "inactive":
                                payload = {
                                "gateway": connector.gateway.name,
                                "device": device.device_name,
                                "connector_id": str(connector.connector_id),
                                "values": values_dict
                            }
                                print(f"   🌐 Sending REST request to {ob_connector.rest_url} [{ob_connector.rest_method}]")
                                
                                if ob_connector.rest_method == "POST":
                                    resp = requests.post(ob_connector.rest_url, json=payload, timeout=10)
                                else:  # GET
                                    resp = requests.get(ob_connector.rest_url, params=payload, timeout=10)

                            else:

                                for rule in rules:
                                    sql = rule.sql
                                    with connection.cursor() as cursor:
                                        cursor.execute(sql)
                                        # fetch results if needed
                                        rows = cursor.fetchall()
                                        column_names = [desc[0] for desc in cursor.description]

                                        # build list of dicts with column_name: value mapping
                                        results_with_columns = [dict(zip(column_names, row)) for row in rows]
                                        print(f"   🌐 Sending REST request to {ob_connector.rest_url} [{ob_connector.rest_method}]")

                                        resp = requests.post(ob_connector.rest_url, json=results_with_columns, timeout=10)
                                        
                            
                            print(f"   ✅ REST Response {resp.status_code}: {resp.text}")
                            ob_connector.status = 'active'
                            ob_connector.save(update_fields=["status"])
                        except Exception as e:
                            print(f"   ❌ REST API error: {e}")
                            ob_connector.status = 'inactive'
                            ob_connector.save(update_fields=["status"])

                    elif ob_connector.connector_type == "openadr-ven":
                        
                        ven_client = openadr_clients.get(ob_connector.gateway.id)
                        if ven_client:
                            for key, val in values_dict.items():
                                ven_client.update(device.device_name, key, val)

                        else:
                            print(f"No VEN client found for connector {ob_connector.gateway.id}")
                    elif ob_connector.connector_type == "ocpp":
                        ocpp_client = ocpp_clients.get(ob_connector.gateway.id)
                        if ocpp_client:
                            # Prepare the meter data for OCPP format
                            meter_data = []
                            timestamp = datetime.utcnow().isoformat() + 'Z'  # UTC ISO format with Zulu time
                            for key, val in values_dict.items():
                                mapped = measurand_mapping.get(key.lower(), {'measurand': 'Energy.Active.Import.Register', 'unit': 'Wh'})
                                meter_data.append({
                                    'timestamp': timestamp,
                                    'value': val,
                                    'unit': mapped['unit'],
                                    'measurand': mapped['measurand']
                                })
                            
                            
                            asyncio.run_coroutine_threadsafe(
                        ocpp_client.send_meter_values(meter_data, device.device_name),
                        ocpp_client.loop
                        )
                    elif ob_connector.connector_type == 'file':
                        ob_connector.status = 'active'
                        ob_connector.save(update_fields=["status"])
                        rules = Rule.objects.filter(stream=connector)
                        if not rules.exists() or rules.actions == "inactive":
                            file_path = ob_connector.file_path
                            print("file_path",file_path)
                            with open(file_path, 'w', encoding='utf-8') as f:
                                json.dump(values_dict, f, ensure_ascii=False, indent=2)
                        else:

                            for rule in rules:
                                sql = rule.sql
                                with connection.cursor() as cursor:
                                    cursor.execute(sql)
                                    # fetch results if needed
                                    rows = cursor.fetchall()
                                    column_names = [desc[0] for desc in cursor.description]

                                    # build list of dicts with column_name: value mapping
                                    results_with_columns = [dict(zip(column_names, row)) for row in rows]
                                with open(file_path, 'w', encoding='utf-8') as f:
                                    json.dump(results_with_columns, f, ensure_ascii=False, indent=2)

     
        else:   
            print(f"   ❌ Device {device.device_name} connection failed")
            device.device_status = "inactive"
            device.save(update_fields=["device_status"])
            

    # Update connector status
    connector.status = "active" if connector_active else "inactive"
    connector.save(update_fields=["status"])

    # Update gateway status
    gateway = connector.gateway
    if IHG_OutboundConnector.objects.filter(gateway=gateway, status="active").exists() or IHG_InboundConnector.objects.filter(gateway=gateway, status="active").exists():
        gateway.status = "active"
    else:
        gateway.status = "inactive"
    gateway.save(update_fields=["status"])


def insert_timeseries_value(connector_table, device_name,  values_dict,max_points):
    # Sanitize connector_table & ts_name to valid SQL identifiers, beware SQL injection

    with connection.cursor() as cursor:
        # Insert new row (simplified)
        columns = ", ".join(values_dict.keys())
        placeholders = ", ".join(["%s"] * (len(values_dict) + 1))  # +1 for device_name

        # Include device_id (or device_name) as first column
        sql = f'INSERT INTO "{connector_table}" (device_id, {columns}) VALUES ({placeholders});'

        # Parameter list: device_name first, then all the values
        params = [device_name] + list(values_dict.values())

        cursor.execute(sql, params)
        if max_points:
            # Delete oldest rows beyond max_points
            cursor.execute(f'SELECT COUNT(*) FROM "{connector_table}";')
            row_count = cursor.fetchone()[0]

            # Calculate how many rows to delete
            excess = row_count - max_points
            if excess > 0:
                # Delete the oldest `excess` rows
                sql_delete = f"""
                    DELETE FROM "{connector_table}"
                    WHERE id IN (
                        SELECT id FROM "{connector_table}"
                        ORDER BY timestamp ASC
                        LIMIT ?
                    );
                """
                cursor.execute(sql_delete, [excess])



def gateway_loop():
    """Loop through connectors using their individual interval values."""
    next_run_times = {}

    while not modbus_thread_stop_event.is_set():
        now = datetime.now()

        connectors = IHG_InboundConnector.objects.all()
        for connector in connectors:
            try:
                # Read interval from DB
                try:
                    interval_sec = int(connector.interval)
                    
                except (ValueError, TypeError):
                    interval_sec = 60  # Default if invalid

                last_run = next_run_times.get(connector.id)

                # If never run or time elapsed, run it
                if not last_run or now >= last_run:
                    print(f"🔄 Running connector {connector.name} every {interval_sec} seconds")
                    
                    read_modbus_timeseries(connector)
                    next_run_times[connector.id] = now + timedelta(seconds=interval_sec)

            except Exception as e:
                print(f"⚠ Error processing connector {connector.name}: {e}")

        # Small sleep to avoid CPU 100%
        time.sleep(5)

def start_modbus_loop():
    global modbus_thread, modbus_thread_stop_event
    if modbus_thread and modbus_thread.is_alive():
        print("Stopping existing Modbus thread before starting a new one")
        stop_modbus_loop()
    modbus_thread_stop_event.clear()
    modbus_thread = threading.Thread(target=gateway_loop, daemon=True)
    modbus_thread.start()
    print("Modbus loop started")

def stop_modbus_loop():
    global modbus_thread, modbus_thread_stop_event
    if modbus_thread and modbus_thread.is_alive():
        print("Stopping Modbus loop...")
        modbus_thread_stop_event.set()
        modbus_thread.join(timeout=10)
        print("Modbus loop stopped")
    modbus_thread = None
