from django.urls import path
from . import views


urlpatterns = [
    # Gateways
    path('', views.gateway_list, name='gateway_list'),
    path('gateway/add/', views.add_gateway, name='add_gateway'),
    path('gateway/<int:pk>/', views.gateway_detail, name='gateway_detail'),
    path('gateway/<int:pk>/edit/', views.edit_gateway, name='edit_gateway'),
    path('gateway/<int:pk>/delete/', views.delete_gateway, name='delete_gateway'),

    path('gateway/<int:gateway_pk>/inbound_connector/add/', views.add_inbound_connector, name='add_inbound_connector'),
    path('inbound_connector/<int:connector_pk>/edit/', views.edit_inbound_connector, name='edit_inbound_connector'),


    path('gateway/<int:gateway_pk>/outbound_connector/add/', views.add_outbound_connector, name='add_outbound_connector'),
    path('outbound_connector/<int:connector_pk>/edit/', views.edit_outbound_connector, name='edit_outbound_connector'),


    path('inbound_connector/<int:connector_pk>/timeseries/add/', views.add_timeseries, name='add_timeseries'),
    path('inbound_connector/<int:connector_pk>/timeseries/delete/<int:ts_pk>/', views.delete_timeseries, name='delete_timeseries'),

path('connector/<str:direction>/<int:connector_pk>/delete/', views.delete_connector, name='delete_connector'),
path('gateway/<int:gateway_id>/import/', views.import_gateway_config, name='import_gateway_config'),
 path("monitor/", views.monitor_view, name="monitor"),
path("api/gateways/", views.api_gateways, name="api_gateways"),
    path("api/connectors/<int:gateway_id>/", views.api_connectors, name="api_connectors"),
    path("api/devices/<int:gateway_id>/", views.api_devices, name="api_devices"),
    path("api/latest-data/<int:device_id>/", views.api_latest_data, name="api_latest_data"),
        path("api/monitor/filters/", views.monitor_filters, name="monitor_filters"),
    path("api/monitor/data/", views.monitor_data, name="monitor_data"),
    path("api/monitor/csv/", views.monitor_csv, name="export-monitor-csv"),



]
