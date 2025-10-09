from django.db import connection
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import IHG_Gateway, IHG_InboundConnector, IHG_OutboundConnector, IHG_Timeseries,Device,IHG_MQTTConfiguration,IHG_ModbusData,IHG_MQTTData,IHG_MQTTTimeseries,IHG_MQTTDevice,IHG_MQTTTopic,RuleChain,Rule

def execute_sql(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)

@receiver(post_save, sender=IHG_InboundConnector)
def create_connector_table(sender, instance, created, **kwargs):
    if created:
        table_name = instance.name.lower().replace('-', '_')  # sanitize name for SQL
        sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT (datetime('now')),
            device_id VARCHAR(255)
        );
        """
        execute_sql(sql)


@receiver(post_delete, sender=IHG_InboundConnector)
def drop_connector_table(sender, instance, **kwargs):
    table_name = instance.name.lower().replace('-', '_')
    sql = f"DROP TABLE IF EXISTS {table_name};"
    execute_sql(sql)