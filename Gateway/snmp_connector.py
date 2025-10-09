
from pysnmp.hlapi import getCmd,  bulkCmd, nextCmd,SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
from django.utils import timezone
from Gateway.models import IHG_InboundConnector, Device,IHG_OutboundConnector,Rule
import threading
import time
from django.db import connection
import requests
import json
import paho.mqtt.client as mqtt
from Gateway.openadr_ven import openadr_clients
from Gateway.ocpp_connector import ocpp_clients 
from Gateway.mappings import measurand_mapping
from datetime import datetime
import asyncio




class SNMPConnector:
    def __init__(self, connector: IHG_InboundConnector):
        self.connector = connector
        # Get SNMP community from the connector config or field
        self.community = connector.configuration
        self.devices = connector.devices.all()

    def snmpget(self, ip, port, oid, community=None):
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(community or self.community),
            UdpTransportTarget((ip, int(port))),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        if errorIndication:
            print("SNMP error:", errorIndication)
        elif errorStatus:
            print("SNMP error status:", errorStatus.prettyPrint(), errorIndex)
        else:
            for varBind in varBinds:
                return varBind[1].prettyPrint()
        return None
    def snmpwalk(self, ip, port, oid, community=None):
        values = []
        for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
            SnmpEngine(),
            CommunityData(community or self.community),
            UdpTransportTarget((ip, int(port))),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if errorIndication or errorStatus:
                break
            for varBind in varBinds:
                values.append(varBind[1].prettyPrint())
        return values
    
    def snmpbulk(self, ip, port, oid, non_repeaters=0, max_repetitions=25, auth_data=None):
        auth_data = auth_data or CommunityData(self.community)
        values = []
        for (errorIndication, errorStatus, errorIndex, varBinds) in bulkCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((ip, int(port))),
            ContextData(),
            non_repeaters,
            max_repetitions,
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if errorIndication or errorStatus:
                print(f"SNMP BULK error on {ip}:{port} {oid}: {errorIndication or errorStatus.prettyPrint()}")
                break
            for varBind in varBinds:
                values.append(varBind[1].prettyPrint())
        return values


    def poll_device(self, device: Device):
        results = {}
        for ts in device.snmp_timeseries.all():
            if ts.method == 'GET':
                results[ts.name] = self.snmpget(device.device_ip, device.device_port, ts.address)
            elif ts.method == 'WALK':
                results[ts.name] = self.snmpwalk(device.device_ip, device.device_port, ts.address)
            elif ts.method == 'BULK':
                results[ts.name] = self.snmpbulk(device.device_ip, device.device_port, ts.address)
         
        return results

    def poll_all_devices(self,connector):
        all_results = {}
        for device in self.devices:
            device_data = self.poll_device(device)
            all_results[getattr(device, 'devicename', device.device_name)] = device_data
        return all_results


# Example threading controlled SNMP polling loop structure

snmp_threads = {}
snmp_thread_stop_events = {}

def send_data_to_outbound_connector(results,connector):
    outbound_connectors = IHG_OutboundConnector.objects.filter(gateway=connector.gateway)

    for ob_connector in outbound_connectors:
        if ob_connector.connector_type == "rest":
            try:
                rules = Rule.objects.filter(stream=connector)
                if not rules.exists() or rules.actions == "inactive":
                    payload = {
                    "gateway": connector.gateway.name,
                    "connector_id": str(connector.connector_id),
                    "values": results
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
            except Exception as e:
                print(f"   ❌ REST API error: {e}")
        elif ob_connector.connector_type == "mqtt":
            config = ob_connector.mqtt_config
      
            topics = config.topics.all()
            mqtt_config = getattr(ob_connector, "mqtt_config", None)
            if not mqtt_config:
                print(f"⚠ No MQTT configuration found for outbound connector {ob_connector.name}")
                return

            # 3️⃣ Prepare MQTT client
            client = mqtt.Client()
            if mqtt_config.username:
                client.username_pw_set(mqtt_config.username, mqtt_config.password or "")

            client.connect(mqtt_config.broker_ip, mqtt_config.port, keepalive=60)

            topics = mqtt_config.topics.all()
            for  topic in topics:
                print("topic",topic.name)
            
                client.publish(topic.name, json.dumps(results))
            client.disconnect()
            print(f"📤 MQTT Published  to topic {topic}")
        elif ob_connector.connector_type == "openadr-ven":
            ven_client = openadr_clients.get(ob_connector.gateway.id)
            if ven_client:
                for device_name , device_data in results.items():
                    for key, val in device_data.items():
                        ven_client.update(device_name, key, val)

            else:
                print(f"No VEN client found for connector {ob_connector.gateway.id}")
        elif ob_connector.connector_type == 'ocpp':
            ocpp_client = ocpp_clients.get(ob_connector.gateway.id)
            if ocpp_client:
                # Prepare the meter data for OCPP format
                
                timestamp = datetime.utcnow().isoformat() + 'Z'  # UTC ISO format with Zulu time
                for device_name , device_data in results.items():
                    meter_data = []
                    for key, val in device_data.items():
                        mapped = measurand_mapping.get(key.lower(), {'measurand': 'Energy.Active.Import.Register', 'unit': 'Wh'})
                        meter_data.append({
                            'timestamp': timestamp,
                            'value': val,
                            'unit': mapped['unit'],
                            'measurand': mapped['measurand']
                        })
                    
                    
                    asyncio.run_coroutine_threadsafe(
                ocpp_client.send_meter_values(meter_data, device_name),
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
                    json.dump(results, f, ensure_ascii=False, indent=2)
                
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

def snmp_loop(connector):
    snmp = SNMPConnector(connector)
    while not snmp_thread_stop_events[connector.id].is_set():
        results = snmp.poll_all_devices(connector)
        # print(f"Results for connector {connector.id}: {results}")
        try:
            with connection.cursor() as cursor:
                for device_name, device_data in results.items():
                    columns = ['device_id']
                    placeholders = ['%s']
                    values = [device_name]

                    for ts_name, value in device_data.items():
                        columns.append(f'"{ts_name}"')  # Quote column names if needed
                        placeholders.append('%s')
                        
                        if isinstance(value, (list, dict)):
                            value = json.dumps(value)
                        values.append(value)

                    sql = f'INSERT INTO "{connector.name}" ({", ".join(columns)}) VALUES ({", ".join(placeholders)});'
                    cursor.execute(sql, values)
            print(f"   ✅ Data inserted into table {connector.name}")
        except Exception as e:  
            print (f"   ❌ Database insert error: {e}")
        send_data_to_outbound_connector(results,connector)
        time.sleep(int(getattr(connector, 'interval', 60)))  # poll interval

def start_snmp_loop():
    global snmp_threads, snmp_thread_stop_events

    connectors = IHG_InboundConnector.objects.filter(connector_type='snmp')

    # Stop any existing running SNMP threads
    for stop_event in snmp_thread_stop_events.values():
        stop_event.set()
    for thread in snmp_threads.values():
        if thread.is_alive():
            thread.join(timeout=10)

    snmp_threads = {}
    snmp_thread_stop_events = {}

    for connector in connectors:
        stop_event = threading.Event()
        snmp_thread_stop_events[connector.id] = stop_event

        thread = threading.Thread(target=snmp_loop, args=(connector,), daemon=True)
        snmp_threads[connector.id] = thread
        thread.start()
        print(f"SNMP loop started for connector {connector.id}")

def stop_snmp_loop():
    global snmp_threads, snmp_thread_stop_events

    for stop_event in snmp_thread_stop_events.values():
        stop_event.set()
    for thread in snmp_threads.values():
        if thread.is_alive():
            thread.join(timeout=10)
            print("SNMP loop stopped")

    snmp_threads = {}
    snmp_thread_stop_events = {}
