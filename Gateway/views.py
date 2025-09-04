import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import IHG_Gateway, IHG_InboundConnector, IHG_OutboundConnector, IHG_Timeseries,Device,IHG_MQTTConfiguration,IHG_ModbusData,IHG_MQTTData,IHG_MQTTTimeseries,IHG_MQTTDevice,IHG_MQTTTopic
from .forms import GatewayForm, InboundConnectorForm, OutboundConnectorForm,MQTTConfigurationForm
import logging
from Gateway import mqtt,modbus
from django.db.models import Count, Q, Max
from django.http import JsonResponse, HttpResponse

import csv
logger = logging.getLogger(__name__)

def gateway_list(request):
    gateways = IHG_Gateway.objects.all().order_by('-created_at')
    return render(request, 'gateway_list.html', {'gateways': gateways})


def add_gateway(request):
    if request.method == 'POST':
        form = GatewayForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Gateway added successfully.')
            return redirect('gateway_list')
    else:
        form = GatewayForm()
    return render(request, 'add_gateway.html', {'form': form})


def edit_gateway(request, pk):
    gateway = get_object_or_404(IHG_Gateway, pk=pk)
    if request.method == 'POST':
        form = GatewayForm(request.POST, instance=gateway)
        if form.is_valid():
            form.save()
            messages.success(request, 'Gateway updated successfully.')
            return redirect('gateway_detail', pk=pk)
    else:
        form = GatewayForm(instance=gateway)
    return render(request, 'edit_gateway.html', {'form': form, 'gateway': gateway})


def delete_gateway(request, pk):
    gateway = get_object_or_404(IHG_Gateway, pk=pk)
    if request.method == 'POST':
        gateway.delete()
        messages.success(request, 'Gateway deleted successfully.')
        modbus.stop_modbus_loop()
        modbus.start_modbus_loop()
        mqtt.stop_mqtt_loop()
        mqtt.start_mqtt_loop()
        return redirect('gateway_list')
    return render(request, 'delete_gateway.html', {'gateway': gateway})


def gateway_detail(request, pk):
    gateway = get_object_or_404(IHG_Gateway, pk=pk)

    inbound_connectors = gateway.inbound_connectors.all()
    outbound_connectors = gateway.outbound_connectors.all()

    context = {
        'gateway': gateway,
        'inbound_connectors': inbound_connectors,
        'outbound_connectors': outbound_connectors,
    }
    return render(request, 'gateway_detail.html', context)


# Inbound Connectors

def add_inbound_connector(request, gateway_pk):
    gateway = get_object_or_404(IHG_Gateway, pk=gateway_pk)
    if request.method == 'POST':
        form = InboundConnectorForm(request.POST)
        if form.is_valid():
            connector = form.save(commit=False)
            connector.gateway = gateway
            connector.is_inbound = True
            connector.save()
            messages.success(request, 'Inbound connector added.')
            return redirect('gateway_detail', pk=gateway_pk)
    else:
        form = InboundConnectorForm()
    return render(request, 'add_connector.html', {'form': form, 'gateway': gateway, 'direction': 'Inbound'})


def get_mqtt_data_nested(mqtt_config):
    topics_dict = {}
    for i, topic in enumerate(mqtt_config.topics.all().order_by('id')):
        devices_dict = {}
        for j, device in enumerate(topic.devices.all().order_by('id')):
            timeseries_dict = {}
            for k, ts in enumerate(device.timeseries.all().order_by('id')):
                timeseries_dict[k] = {
                    'key': ts.key,
                    'type': ts.type
                }
            devices_dict[j] = {
                'device_name': device.device_name,
                'device_id': device.device_id,
                'timeseries': timeseries_dict,
            }
        topics_dict[i] = {
            'name': topic.name,
            'devices': devices_dict,
        }
    return topics_dict

def edit_inbound_connector(request, connector_pk):
    connector = get_object_or_404(IHG_InboundConnector, pk=connector_pk)
    mqtt_config = None
    mqtt_form = None
    mqtt_topics_nested = {}
    if connector.connector_type == "mqtt":
        mqtt_config, _ = IHG_MQTTConfiguration.objects.get_or_create(connector_inbound=connector)
        
        if mqtt_config:
            # Build nested structure for template
            mqtt_topics_nested = get_mqtt_data_nested(mqtt_config)

    if request.method == 'POST':
        form = InboundConnectorForm(request.POST, instance=connector)

        if form.is_valid():
            connector = form.save()

            if connector.connector_type == "mqtt":
                mqtt_form = MQTTConfigurationForm(request.POST, instance=mqtt_config)
                
                if mqtt_form.is_valid():
                    mqtt_form.instance.connector_inbound = connector
                    # Save MQTT general config (broker IP, port, credentials)
                    mqtt_form.save()

                    # Clear existing topics, devices, and timeseries to replace
                    IHG_MQTTTopic.objects.filter(mqtt_config=mqtt_config).delete()

                    # Loop through topics in POST
                    # Expect topics indexed as: topics[0][name], topics[0][devices][0][name], etc.
                    post = request.POST

                    topic_keys = [key for key in post if key.startswith("topics[") and key.endswith("][name]")]
                    # Extract topic indices like '0', '1' from keys 'topics[0][name]'
                    topic_indices = sorted(set([key.split('[')[1].split(']')[0] for key in topic_keys]))

                    for ti in topic_indices:
                        topic_name = post.get(f"topics[{ti}][name]", "").strip()
                        if not topic_name:
                            continue

                        # Create topic
                        topic_obj = IHG_MQTTTopic.objects.create(mqtt_config=mqtt_config, name=topic_name)

                        # Find device indices under this topic
                        device_prefix = f"topics[{ti}][devices]"
                        device_keys = [key for key in post if key.startswith(device_prefix) and key.endswith("][name]")]
                        device_indices = sorted(set([key.split('[')[3].split(']')[0] for key in device_keys]))

                        for di in device_indices:
                            device_name = post.get(f"topics[{ti}][devices][{di}][name]", "").strip()
                            if not device_name:
                                continue

                            device_id = post.get(f"topics[{ti}][devices][{di}][id]", "").strip() # If device_id field exists, adjust accordingly

                            # Create device linked to topic
                            device_obj = IHG_MQTTDevice.objects.create(
                                topic=topic_obj,
                                device_name=device_name,
                                device_id=device_id
                            )

                            # Get timeseries under this device
                            ts_key_prefix = f"topics[{ti}][devices][{di}][timeseries]"
                            # Find all keys for timeseries keys
                            ts_key_keys = [k for k in post if k.startswith(ts_key_prefix) and k.endswith("[key]")]
                            ts_indices = sorted(set([k.split('[')[5].split(']')[0] for k in ts_key_keys]))

                            for tsi in ts_indices:
                                ts_key = post.get(f"topics[{ti}][devices][{di}][timeseries][{tsi}][key]", "").strip()
                                ts_type = post.get(f"topics[{ti}][devices][{di}][timeseries][{tsi}][type]", "").strip()

                                if ts_key:
                                    IHG_MQTTTimeseries.objects.create(
                                        device=device_obj,
                                        key=ts_key,
                                        type=ts_type if ts_type else 'String',
                                    )
                mqtt.stop_mqtt_loop()
                mqtt.start_mqtt_loop()
            elif connector.connector_type == "modbus":
                # Existing modbus handling (unchanged)
                Device.objects.filter(connector=connector).delete()

                devices_data = [key for key in request.POST if key.startswith("devices[")]
                device_indices = sorted(set([key.split('[')[1].split(']')[0] for key in devices_data]))

                for idx in device_indices:
                    name = request.POST.get(f"devices[{idx}][name]")
                    dev_id = request.POST.get(f"devices[{idx}][id]")
                    dev_ip = request.POST.get(f"devices[{idx}][ip]")
                    dev_port = request.POST.get(f"devices[{idx}][port]")

                    if not name or not dev_id:
                        continue

                    device_obj = Device.objects.create(
                        connector=connector,
                        device_name=name,
                        device_id=dev_id,
                        device_ip=dev_ip,
                        device_port=dev_port
                    )

                    ts_names = request.POST.getlist(f"devices[{idx}][ts][name][]")
                    ts_scales = request.POST.getlist(f"devices[{idx}][ts][scale][]")
                    ts_addresses = request.POST.getlist(f"devices[{idx}][ts][address][]")
                    ts_byte_orders = request.POST.getlist(f"devices[{idx}][ts][byte_order][]")
                    ts_data_types = request.POST.getlist(f"devices[{idx}][ts][data_type][]")

                    for t in range(len(ts_names)):
                        if ts_names[t].strip():
                            IHG_Timeseries.objects.create(
                                device=device_obj,
                                name=ts_names[t].strip(),
                                scale=float(ts_scales[t]),
                                address=ts_addresses[t].strip(),
                                byte_order=ts_byte_orders[t].strip(),
                                data_type=ts_data_types[t].strip()
                            )
                modbus.stop_modbus_loop()
                modbus.start_modbus_loop()
            messages.success(request, "Inbound connector updated successfully.")
            return redirect('edit_inbound_connector', connector_pk=connector_pk)

    else:
        form = InboundConnectorForm(instance=connector)

    devices = Device.objects.filter(connector=connector).prefetch_related('timeseries')
    return render(request, 'inbound_connector.html', {
        'connector': connector,
        'devices': devices,
        'form': form,
        'mqtt_data': mqtt_config,
        'mqtt_form': mqtt_form,
        'mqtt_topics_nested':mqtt_topics_nested
    })


def add_outbound_connector(request, gateway_pk):
    gateway = get_object_or_404(IHG_Gateway, pk=gateway_pk)
    if request.method == 'POST':
        form = OutboundConnectorForm(request.POST)
        if form.is_valid():
            connector = form.save(commit=False)
            connector.gateway = gateway
            connector.is_inbound = False
            connector.save()
            messages.success(request, 'Outbound connector added.')
            return redirect('gateway_detail', pk=gateway_pk)
    else:
        form = OutboundConnectorForm()
    return render(request, 'add_connector.html', {'form': form, 'gateway': gateway, 'direction': 'outbound'})



def edit_outbound_connector(request, connector_pk):
    connector = get_object_or_404(IHG_OutboundConnector, pk=connector_pk)

    mqtt_config = None
    mqtt_topics_list = []
    if connector.connector_type == "mqtt":
        mqtt_config, _ = IHG_MQTTConfiguration.objects.get_or_create(connector_outbound=connector)
        mqtt_topics_list = list(IHG_MQTTTopic.objects.filter(mqtt_config=mqtt_config).values_list('name', flat=True))

    if request.method == 'POST':
        # Force connector_type to its original value to avoid tampering
        post_data = request.POST.copy()
        post_data['connector_type'] = connector.connector_type

        form = OutboundConnectorForm(post_data, instance=connector)

        if form.is_valid():
            connector = form.save()
            gateway_id = connector.gateway.id
            in_connector = IHG_InboundConnector.objects.get(gateway=gateway_id)
            if connector.connector_type == "mqtt":
                mqtt_form = MQTTConfigurationForm(request.POST, instance=mqtt_config)
                if mqtt_form.is_valid():
                    mqtt_form.instance.connector_outbound = connector
                    mqtt_form.save()
                    # Clear all previous topics for this config
                    IHG_MQTTTopic.objects.filter(mqtt_config=mqtt_config).delete()
                    # Get topics from POST list (array of inputs)
                    topics_list = request.POST.getlist('topics[]')
                    for topic_name in topics_list:
                        topic_name = topic_name.strip()
                        if topic_name:
                            IHG_MQTTTopic.objects.create(mqtt_config=mqtt_config, name=topic_name)
                    # Reload topics for display
                    mqtt_topics_list = list(IHG_MQTTTopic.objects.filter(mqtt_config=mqtt_config).values_list('name', flat=True))
                
            elif connector.connector_type == "rest":
                
                connector.rest_url = post_data.get("rest_url")
                connector.rest_method = post_data.get("rest_method", "POST")
                connector.save(update_fields=["rest_url", "rest_method"])
            elif connector.connector_type == 'openadr-ven':
                connector.rest_url = post_data.get("rest_url")
                
                connector.save(update_fields=["rest_url"])
            if in_connector.connector_type == "modbus":
                modbus.stop_modbus_loop()
                modbus.start_modbus_loop()
            elif in_connector.connector_type == 'mqtt':
                mqtt.stop_mqtt_loop()
                mqtt.start_mqtt_loop()


                
            print('Outbound connector updated.')
            return redirect('gateway_detail', pk=connector.gateway.pk)
    else:
        form = OutboundConnectorForm(instance=connector)

    mqtt_data = {
        'broker': mqtt_config.broker_ip if mqtt_config else '',
        'port': mqtt_config.port if mqtt_config else 1883,
        'username': mqtt_config.username if mqtt_config else '',
        'password': mqtt_config.password if mqtt_config else '',
        'topics': mqtt_topics_list if mqtt_topics_list else [],
    }

    return render(request, 'outbound_connector.html', {
        'connector': connector,
        'form': form,
        'mqtt_data': mqtt_data,
    })



def delete_timeseries(request, connector_pk, ts_pk):
    ts = get_object_or_404(IHG_Timeseries, pk=ts_pk, connector_id=connector_pk)
    if request.method == 'POST':
        ts.delete()
        messages.success(request, 'Timeseries deleted.')
    return redirect('edit_inbound_connector', connector_pk=connector_pk)


def delete_connector(request, direction, connector_pk):
    """
    Deletes inbound or outbound connector depending on the direction param.
    direction should be 'inbound' or 'outbound' (case-insensitive).
    """
    direction = direction.lower()
    if direction == 'inbound':
        model = IHG_InboundConnector
        direction_display = 'Inbound'
    elif direction == 'outbound':
        model = IHG_OutboundConnector
        direction_display = 'Outbound'
    else:
        messages.error(request, 'Invalid connector direction specified.')
        return redirect('gateway_list')

    connector = get_object_or_404(model, pk=connector_pk)
    gateway_pk = connector.gateway.pk
    connector_name = connector.name
    connector.delete()

    messages.success(request, f"{direction_display} connector '{connector_name}' deleted successfully.")
    return redirect('gateway_detail', pk=gateway_pk)


def add_timeseries(request, connector_pk):
    connector = get_object_or_404(IHG_InboundConnector, pk=connector_pk)
    if request.method == 'POST':
        # Receive dynamically added timeseries fields
        names = request.POST.getlist('new_ts_name[]')
        scales = request.POST.getlist('new_ts_scale[]')
        addresses = request.POST.getlist('new_ts_address[]')
        byte_orders = request.POST.getlist('new_ts_byte_order[]')
        data_types = request.POST.getlist('new_ts_data_type[]')

        for i in range(len(names)):
            if names[i].strip():
                IHG_Timeseries.objects.create(
                    connector=connector,
                    name=names[i].strip(),
                    scale=scales[i].strip(),
                    address=addresses[i].strip(),
                    byte_order=byte_orders[i].strip(),
                    data_type=data_types[i].strip(),
                )
        messages.success(request, 'Timeseries added successfully.')
    return redirect('gateway_app:edit_inbounf_connector', connector_pk=connector_pk)



# def import_gateway_config(request, gateway_id):
#     gateway = get_object_or_404(IHG_Gateway, id=gateway_id)

#     try:
#         file_data = request.FILES['config_file'].read().decode('utf-8')
#         config_json = json.loads(file_data)
#         IHG_InboundConnector.objects.filter(gateway=gateway, connector_type='modbus', is_inbound=True).delete()
#         IHG_OutboundConnector.objects.filter(gateway=gateway, connector_type='mqtt').delete()

#         # --- Handle Modbus Inputs (Inbound Connectors) ---
#         modbus_inputs = config_json.get('inputs', {}).get('modbus', [])
#         for mb in modbus_inputs:
#             inbound, created = IHG_InboundConnector.objects.get_or_create(
#                 gateway=gateway,
#                 name=mb.get('name'),
#                 defaults={
#                     'connector_type': 'modbus',
#                     'is_inbound': True,
#                     'configuration': mb
#                 }
#             )
#             # Update configuration if already exists
#             if not created:
#                 inbound.configuration = mb
#                 inbound.save()

#             # Create Device(s) from tags if available
#             tags = mb.get('tags', {})
#             controller = mb.get('controller', [])
#             print("controller",controller)
#             if controller and controller.startswith('tcp://'):
#                 # extract IP and port
#                 ip_port = controller[6:]  # after tcp://
#                 print("ip_port",ip_port)
#                 if ':' in ip_port:
#                     ip, port_str = ip_port.split(':', 1)
#                     port = int(port_str)
#                 else:
#                     ip = ip_port
#                     port = 0000
#             else:
#                 ip = '127.0.0.1'
#                 port = 0000
#             device_id = tags.get('device_id')
#             device_name = tags.get('device_name')

#             if device_id and device_name:
#                 device, _ = Device.objects.get_or_create(
#                     connector=inbound,
#                     device_id=device_id,
#                     device_ip=ip,
#                     device_port=port,
#                     defaults={'device_name': device_name}
#                 )
#             else:
#                 device = None  # No device info provided, skip timeseries

#             # Save holding registers as Timeseries linked to Device
#             if device:
#                 for reg in mb.get('holding_registers', []):
#                     IHG_Timeseries.objects.update_or_create(
#                         device=device,
#                         name=reg.get('name'),
#                         defaults={
#                             'scale': float(reg.get('scale', 1.0)),
#                             'address': ",".join(map(str, reg.get('address', []))),
#                             'byte_order': reg.get('byte_order'),
#                             'data_type': reg.get('data_type'),
#                         }
#                     )

#         # --- Handle MQTT Outputs (Outbound Connectors) ---
#         mqtt_outputs = config_json.get('outputs', {}).get('mqtt', [])
#         for mqtt in mqtt_outputs:
#             # Use a unique name for outbound connector (e.g. client_id or topic)
#             name = f"Mqtt{mqtt.get('qos')}"


#             outbound, created = IHG_OutboundConnector.objects.get_or_create(
#                 gateway=gateway,
#                 name=name,
#                 defaults={
#                     'connector_type': 'mqtt',
#                     'is_inbound': False,
#                     'configuration': mqtt
#                 }
#             )
#             # Update configuration if exists
#             if not created:
#                 outbound.configuration = mqtt
#                 outbound.save()

#             # Update or create MQTT configuration
#             server_url = mqtt.get('servers', [None])[0]
#             if server_url and server_url.startswith('tcp://'):
#                 ip_port = server_url[6:]
#                 if ':' in ip_port:
#                     ip, port_str = ip_port.split(':', 1)
#                     port = int(port_str)
#                 else:
#                     ip = ip_port
#                     port = 1883
#             else:
#                 ip = '127.0.0.1'
#                 port = 1883

#             IHG_MQTTConfiguration.objects.update_or_create(
#                 connector=outbound,
#                 defaults={
#                     'broker_ip': ip,
#                     'port': port,
#                     'interval': '60s',  # default, adjust if config has it
#                     'username': mqtt.get('username'),
#                     'password': mqtt.get('password'),
#                     'topic': mqtt.get('topic', ''),
#                 }
#             )

#         messages.success(request, "Configuration imported successfully.")

#     except Exception as e:
#         messages.error(request, f"Error importing configuration: {e}")

#     return redirect('gateway_detail', pk=gateway_id)

def import_gateway_config(request, gateway_id):
    gateway = get_object_or_404(IHG_Gateway, id=gateway_id)

    try:
        file_data = request.FILES['config_file'].read().decode('utf-8')
        config_json = json.loads(file_data)

        # Cleanup old connectors for this gateway
        IHG_InboundConnector.objects.filter(gateway=gateway).delete()
        IHG_OutboundConnector.objects.filter(gateway=gateway).delete()

        # --- Handle Inbound Connectors ---
        inputs = config_json.get("inputs", {})

        # ✅ Modbus Inbound
        for mb in inputs.get("modbus", []):
            inbound, _ = IHG_InboundConnector.objects.update_or_create(
                gateway=gateway,
                name=mb.get("name"),
                defaults={
                    "connector_type": "modbus",
                    "is_inbound": True,
                    "configuration": mb
                }
            )

            # Devices + timeseries setup
            tags = mb.get("tags", {})
            controller = mb.get("controller", "")
            if controller.startswith("tcp://"):
                ip_port = controller[6:]
                if ":" in ip_port:
                    ip, port_str = ip_port.split(":", 1)
                    port = int(port_str)
                else:
                    ip, port = ip_port, 502
            else:
                ip, port = "127.0.0.1", 502

            device_id = tags.get("device_id")
            device_name = tags.get("device_name")

            if device_id and device_name:
                device, _ = Device.objects.get_or_create(
                    connector=inbound,
                    device_id=device_id,
                    defaults={"device_name": device_name, "device_ip": ip, "device_port": port}
                )

                # Create timeseries from holding registers
                for reg in mb.get("holding_registers", []):
                    IHG_Timeseries.objects.update_or_create(
                        device=device,
                        name=reg.get("name"),
                        defaults={
                            "scale": float(reg.get("scale", 1.0)),
                            "address": ",".join(map(str, reg.get("address", []))),
                            "byte_order": reg.get("byte_order"),
                            "data_type": reg.get("data_type"),
                        }
                    )

        # ✅ MQTT Inbound
        for mqtt in inputs.get("mqtt", []):
            inbound, _ = IHG_InboundConnector.objects.update_or_create(
                gateway=gateway,
                name=mqtt.get("name", "Inbound MQTT"),
                defaults={
                    "connector_type": "mqtt",
                    "is_inbound": True,
                    "configuration": mqtt
                }
            )

            server_url = mqtt.get("servers", [None])[0]
            if server_url and server_url.startswith("tcp://"):
                ip_port = server_url[6:]
                if ":" in ip_port:
                    ip, port_str = ip_port.split(":", 1)
                    port = int(port_str)
                else:
                    ip, port = ip_port, 1883
            else:
                ip, port = "127.0.0.1", 1883

            IHG_MQTTConfiguration.objects.update_or_create(
                connector_inbound=inbound,
                defaults={
                    "broker_ip": ip,
                    "port": port,
                    "username": mqtt.get("username",''),
                    "password": mqtt.get("password",''),
                    "topics": mqtt.get("topic", ""),
                    "interval": mqtt.get("interval", "60s"),
                }
            )

        # --- Handle Outbound Connectors ---
        outputs = config_json.get("outputs", {})

        # ✅ MQTT Outbound
        for mqtt in outputs.get("mqtt", []):
            outbound, _ = IHG_OutboundConnector.objects.update_or_create(
                gateway=gateway,
                name=mqtt.get("name", "Outbound MQTT"),
                defaults={
                    "connector_type": "mqtt",
                    "is_inbound": False,
                    "configuration": mqtt
                }
            )

            server_url = mqtt.get("servers", [None])[0]
            if server_url and server_url.startswith("tcp://"):
                ip_port = server_url[6:]
                if ":" in ip_port:
                    ip, port_str = ip_port.split(":", 1)
                    port = int(port_str)
                else:
                    ip, port = ip_port, 1883
            else:
                ip, port = "127.0.0.1", 1883

            IHG_MQTTConfiguration.objects.update_or_create(
                connector_outbound=outbound,
                defaults={
                    "broker_ip": ip,
                    "port": port,
                    "username": mqtt.get("username",''),
                    "password": mqtt.get("password",''),
                    "topics": mqtt.get("topic", ""),
                    "interval": mqtt.get("interval", "60s"),
                }
            )

        # ✅ REST Outbound
        for rest in outputs.get("rest", []):
            IHG_OutboundConnector.objects.update_or_create(
                gateway=gateway,
                name=rest.get("name", "Outbound REST"),
                defaults={
                    "connector_type": "rest",
                    "is_inbound": False,
                    "rest_url": rest.get("url"),
                    "rest_method": rest.get("method", "POST"),
                    "configuration": rest
                }
            )

        messages.success(request, "Configuration imported successfully ✅")

    except Exception as e:
        messages.error(request, f"Error importing configuration: {e}")

    return redirect("gateway_detail", pk=gateway_id)


def monitor_view(request):
    return render(request, "monitor.html")
# 1. Get all Gateways
def api_gateways(request):
    gateways = list(IHG_Gateway.objects.values("id", "name", "status"))
    return JsonResponse({"gateways": gateways})


# 2. Get all Connectors for a Gateway
def api_connectors(request, gateway_id):
    connectors = list(
        IHG_InboundConnector.objects.filter(gateway_id=gateway_id)
        .values("id", "name", "status")
    )
    return JsonResponse({"connectors": connectors})


# 3. Get all Devices for a Connector
def api_devices(request, gateway_id):
    connectors = IHG_InboundConnector.objects.filter(gateway_id=gateway_id)
    if connectors.filter(connector_type="modbus").exists():
        devices = list(
            Device.objects.filter(connector__gateway_id=gateway_id)
            .values("id", "device_name", "device_status")
        )
        print(devices,devices)
        return JsonResponse({"devices": devices})

    # Otherwise, if any connector is mqtt
    elif connectors.filter(connector_type="mqtt").exists():
        # Get MQTT configs linked to inbound connectors of this gateway
        mqtt_configs = IHG_MQTTConfiguration.objects.filter(connector_inbound__gateway_id=gateway_id)
        # Find distinct device names in the mqtt data tied to these configs
        device_names = (
            IHG_MQTTData.objects
            .filter(config__in=mqtt_configs)
            .values_list("id","device_name", flat=True)
            .distinct()
        )
        print("device_names",list(device_names))
        return JsonResponse({"devices": list(device_names)})

    return JsonResponse({"devices": devices})


# 4. Get latest Modbus data for a Device
def api_latest_data(request, device_id):
    latest_data = (
        IHG_ModbusData.objects.filter(timeseries__device_id=device_id)
        .order_by("timeseries_id", "-timestamp")
        .distinct("timeseries_id")
        .values(
            "timeseries__name",
            "value",
            "timestamp"
        )
    )
    return JsonResponse({"data": list(latest_data)})

from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce

from django.db.models import OuterRef, Subquery, Q

def get_devices_data_for_gateway(gateway_id,device_id=None):
    # Get all devices for gateway
    print("devices",gateway_id,device_id)
    if device_id:
        devices=Device.objects.filter(connector__gateway_id=gateway_id,id=device_id)
    else:
        devices = Device.objects.filter(connector__gateway_id=gateway_id)
    print("devices",devices)


    # Annotate each device with its last communication time (max timestamp from modbus data)
    last_comm_qs = IHG_ModbusData.objects.filter(
        timeseries__device=OuterRef('pk'),
        value__isnull=False
    ).order_by().values('timeseries__device').annotate(
        last_comm=Max('timestamp')
    ).values('last_comm')

    devices = devices.annotate(
        last_communication=Subquery(last_comm_qs[:1])
    )

    # Latest non-null modbus data per timeseries
    latest_modbus = IHG_ModbusData.objects.filter(
        timeseries=OuterRef('pk'),
        value__isnull=False
    ).order_by('-timestamp')

    # Annotate each timeseries with latest value and timestamp
    timeseries_with_latest = IHG_Timeseries.objects.filter(
        device__in=devices
    ).annotate(
        latest_value=Subquery(latest_modbus.values('value')[:1]),
        latest_timestamp=Subquery(latest_modbus.values('timestamp')[:1])
    ).filter(
        latest_value__isnull=False
    ).select_related('device')

    # Build flat list for frontend
    result = []

    # Build a dict of device last communication times for quick lookup
    device_last_comm = {d.device_name: d.last_communication for d in devices}

    for ts in timeseries_with_latest:
        last_comm = device_last_comm.get(ts.device.device_name)
        result.append({
            "device_name": ts.device.device_name,
            "key": ts.name,
            "value": ts.latest_value,
            "last_update_time": ts.latest_timestamp.isoformat() if ts.latest_timestamp else None,
            "device_last_communication": last_comm.isoformat() if last_comm else None,  # Include device last comm time
        })

    return result


def monitor_filters(request):
    gateways = list(IHG_Gateway.objects.values("id", "name"))
    devices = list(Device.objects.values("id", "device_name"))

    active_devices_count = Device.objects.filter(device_status="active").count()

    return JsonResponse({
        "gateways": gateways,
        "devices": devices,
        "meta": {
            "gateways": len(gateways),
            "devices": len(devices),
            "active_devices": active_devices_count
        }
    })


def monitor_data(request):
    gateway_id = request.GET.get("gateway")
    device_id = request.GET.get("device")
    if not gateway_id:
        return JsonResponse({"error": "gateway parameter is required"}, status=400)

    if device_id:
        
        data = get_devices_data_for_gateway(gateway_id,device_id)
    else:
        data = get_devices_data_for_gateway(gateway_id)
    
    
    return JsonResponse({"data": data})


def monitor_csv(request):
    gateway_id = request.GET.get("gateway")
    device_id = request.GET.get("device", "").strip()
    limit = int(request.GET.get("limit", "50"))

    if not gateway_id:
        return HttpResponse("Missing gateway parameter", status=400)

    try:
        gateway = IHG_Gateway.objects.get(id=gateway_id)
    except IHG_Gateway.DoesNotExist:
        return HttpResponse("Invalid gateway", status=404)

    # Get devices under this gateway
    devices_qs = Device.objects.filter(connector__gateway=gateway)

    if device_id:
        devices_qs = devices_qs.filter(id=device_id)

    # Prepare CSV response
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="monitor_data.csv"'

    writer = csv.writer(response)
    writer.writerow(["Gateway", "Device", "Timeseries", "Value", "Timestamp"])

    for device in devices_qs:
        timeseries_qs = device.timeseries.all()
        for ts in timeseries_qs:
            modbus_data = ts.modbus_data.all()[:limit]  # latest N values
            for row in modbus_data:
                writer.writerow([
                    gateway.name,
                    device.device_name,
                    ts.name,
                    row.value,
                    row.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                ])

    return response
