from django.db import models
import uuid
from django.utils import timezone

class IHG_Gateway(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    )
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='inactive')

    def __str__(self):
        return self.name


class IHG_ConnectorBase(models.Model):
    TYPE_CHOICES = (
        ('modbus', 'Modbus'),
        ('mqtt', 'MQTT'),
        ('http', 'HTTP'),
        ('custom', 'Custom'),
    )
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    )
    name = models.CharField(max_length=120)
    connector_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    connector_id = models.UUIDField(default=uuid.uuid4,editable=True)
    is_inbound = models.BooleanField(default=True, help_text="True=Inbound, False=Outbound")
    configuration = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='inactive')
    interval = models.CharField(max_length=20, default="60")
    maximum_data_points = models.CharField(max_length=20, default="100")

    class Meta:
        abstract = True

    def __str__(self):
        direction = 'inbound' if self.is_inbound else 'outbound'
        return f"{self.name} ({self.connector_type}, {direction})"


class IHG_InboundConnector(IHG_ConnectorBase):
    INBOUND_TYPE_CHOICES = (
        ('modbus', 'Modbus'),
        ('mqtt', 'MQTT'),
        ('rest', 'REST'),
        ('custom', 'Custom')
    )

    connector_type = models.CharField(
        max_length=30,
        choices=INBOUND_TYPE_CHOICES
    )
    gateway = models.ForeignKey(
        IHG_Gateway,
        related_name='inbound_connectors',
        on_delete=models.CASCADE,
    )
    
    class Meta:
        verbose_name = "Inbound Connector"
        verbose_name_plural = "Inbound Connectors"


class IHG_OutboundConnector(IHG_ConnectorBase):
    OUTBOUND_TYPE_CHOICES = (
        ('mqtt', 'MQTT'),
        ("rest", "REST"),   
        # ("openadr-ven", "OpenADR-VEN"),   
        ('custom', 'Custom'),
    )

    connector_type = models.CharField(
        max_length=30,
        choices=OUTBOUND_TYPE_CHOICES
    )
    gateway = models.ForeignKey(
        IHG_Gateway,
        related_name='outbound_connectors',
        on_delete=models.CASCADE,
    )
    rest_url = models.URLField(blank=True, null=True)   # ✅ For REST target
    rest_method = models.CharField(
        max_length=10,
        choices=[("GET", "GET"), ("POST", "POST")],
        default="POST"
    )

    class Meta:
        verbose_name = "Outbound Connector"
        verbose_name_plural = "Outbound Connectors"

class Device(models.Model):
    connector = models.ForeignKey(IHG_InboundConnector, related_name="devices", on_delete=models.CASCADE)
    device_name = models.CharField(max_length=100)
    device_id = models.CharField(max_length=100)
    device_ip = models.GenericIPAddressField(protocol='both', unpack_ipv4=True,default='127.0.0.1')
    device_port = models.PositiveIntegerField(default=0000)
    device_status = models.CharField(max_length=10, default='inactive')


class IHG_Timeseries(models.Model):
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='timeseries'  # <-- This is the key fix
    )
    name = models.CharField(max_length=100)
    scale = models.FloatField()
    address = models.CharField(max_length=100)
    byte_order = models.CharField(
        max_length=20,
        choices=[
            ('AB', 'AB'), ('BA', 'BA'), ('ABCD', 'ABCD'),
            ('DCBA', 'DCBA'), ('CDAB', 'CDAB'), ('GHEFCDAB', 'GHEFCDAB'),
        ]
    )
    data_type = models.CharField(
        max_length=50,
        choices=[
            ('UINT16', 'UINT16'),
            ('UINT32', 'UINT32'),
            ('UINT64', 'UINT64'),
            ('INT16', 'INT16'),
            ('INT32', 'INT32'),
            ('INT64', 'INT64'),
            ('FLOAT32-IEEE', 'FLOAT32-IEEE'),
            ('FLOAT64-IEEE', 'FLOAT64-IEEE'),
            ('FLOAT32', 'FLOAT32'),
            ('FIXED', 'FIXED'),
            ('UFIXED', 'UFIXED'),
            ('DOUBLE', 'DOUBLE'),
        ]
    )

class IHG_MQTTConfiguration(models.Model):
    connector_inbound = models.OneToOneField(
        IHG_InboundConnector, on_delete=models.CASCADE, related_name="mqtt_config", null=True, blank=True
    )
    connector_outbound = models.OneToOneField(
        IHG_OutboundConnector, on_delete=models.CASCADE, related_name="mqtt_config", null=True, blank=True
    )
    broker_ip = models.GenericIPAddressField(default='127.0.0.1')
    port = models.PositiveIntegerField(default=1883)
    interval = models.CharField(max_length=20, default="60s",blank=True,null=True)  # e.g., "60s"
    username = models.CharField(max_length=100, blank=True, default='')
    password = models.CharField(max_length=100, blank=True, default='')


    def __str__(self):
        if self.connector_inbound:
            return f"MQTT Config (Inbound - {self.connector_inbound.name})"
        if self.connector_outbound:
            return f"MQTT Config (Outbound - {self.connector_outbound.name})"
        return "MQTT Config"
    
class IHG_ModbusData(models.Model):
    timeseries = models.ForeignKey("IHG_Timeseries", on_delete=models.CASCADE, related_name="modbus_data")
    timestamp = models.DateTimeField(auto_now_add=True)
    value = models.FloatField()

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timeseries.name} - {self.value} at {self.timestamp}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        # --- Enforce maximum_data_points ---
        connector = self.timeseries.device.connector  # 🔗 goes back to IHG_InboundConnector
       
        max_points = int(connector.maximum_data_points)
        if max_points:
            qs = IHG_ModbusData.objects.filter(timeseries__device__connector=connector).order_by("-timestamp")
            if qs.count() > max_points:
                # delete oldest extra records
                ids_to_delete = qs[max_points:].values_list("id", flat=True)
                IHG_ModbusData.objects.filter(id__in=ids_to_delete).delete()

class IHG_MQTTTopic(models.Model):
    mqtt_config = models.ForeignKey(
        IHG_MQTTConfiguration, related_name="topics",
        on_delete=models.CASCADE
    )
    name = models.CharField(max_length=255)  # e.g. "sensor/+/data"
    def __str__(self):
        return self.name

class IHG_MQTTDevice(models.Model):
    topic = models.ForeignKey(
        IHG_MQTTTopic,
        related_name="devices",
        on_delete=models.CASCADE,
    )
    device_name = models.CharField(max_length=100)
    device_id = models.CharField(max_length=100, blank=True, null=True)
    def __str__(self):
        return self.device_name

class IHG_MQTTTimeseries(models.Model):
    device = models.ForeignKey(
        IHG_MQTTDevice,
        related_name="timeseries",
        on_delete=models.CASCADE,
    )
    key = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=[
        ('String', 'String'), ('Integer', 'Integer'), ('Double', 'Double'), ('Boolean', 'Boolean')
    ])

class IHG_MQTTData(models.Model):
    device = models.ForeignKey(
        IHG_MQTTDevice,
        on_delete=models.CASCADE,
        related_name="mqtt_data"
    )
    key = models.CharField(max_length=150)
    value = models.FloatField()
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.device.device_name} | {self.key}={self.value} @ {self.timestamp}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # If you want to enforce max data points, you must get it from device->connector
        if self.device and self.device.topic and self.device.topic.mqtt_config:
            connector = getattr(self.device.topic.mqtt_config, 'connector_inbound', None)
        
        if connector:
            max_points = int(getattr(connector, "maximum_data_points", 0) or 0)
        if max_points:
            qs = IHG_MQTTData.objects.filter(device=self.device).order_by("-timestamp")
            count = qs.count()
            if count > max_points:
                ids_to_delete = qs[max_points:].values_list("id", flat=True)
                IHG_MQTTData.objects.filter(id__in=ids_to_delete).delete()
